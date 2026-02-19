import os
import sqlite3
from datetime import date
from flask import Flask, render_template, request, redirect, url_for, flash
from school_calendar import calculate_girls_food, calculate_days_until_25

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
DATABASE = os.environ.get('DATABASE_PATH', 'budget.db')

# ---------------------------------------------------------------------------
# Expense/income template — mirrors Column C of the Excel file.
# amount=None means the field is variable (filled in manually or calculated).
# ---------------------------------------------------------------------------
EXPENSE_TEMPLATE = [
    # --- Income ---
    dict(name='משכורת תום',               name_en="Tom's salary",              amount=None,   debit_day=None, is_income=1, sort_order=1),
    dict(name='משכורת תמרי',              name_en="Tamari's salary",            amount=1200.0, debit_day=None, is_income=1, sort_order=2),
    dict(name='CAF ילדים',                name_en='CAF children',               amount=150.0,  debit_day=None, is_income=1, sort_order=3),
    dict(name='CAF דירה',                 name_en='CAF housing',                amount=None,   debit_day=None, is_income=1, sort_order=4),
    dict(name='לקבל חזרה מביטוח רפואי',  name_en='Medical insurance refund',   amount=None,   debit_day=None, is_income=1, sort_order=5),
    dict(name='החזר מהעבודה',             name_en='Work reimbursement',         amount=None,   debit_day=None, is_income=1, sort_order=6),
    # --- Expenses ---
    dict(name='שכר דירה',                 name_en='Rent',                       amount=1683.0, debit_day=28,   is_income=0, sort_order=7),
    dict(name='חשבון חשמל',              name_en='Electricity (EDF)',          amount=151.0,  debit_day=16,   is_income=0, sort_order=8),
    dict(name='נאביגו',                   name_en='Navigo (transit)',            amount=230.0,  debit_day=6,    is_income=0, sort_order=9),
    dict(name='טלפונים ואינטרנט',         name_en='Phones & internet',          amount=95.0,   debit_day=None, is_income=0, sort_order=10),
    dict(name='ביטוח דירה',              name_en='Home insurance',             amount=13.0,   debit_day=19,   is_income=0, sort_order=11),
    dict(name='אוכל בנות',               name_en="Girls' school food",         amount=None,   debit_day=5,    is_income=0, sort_order=12),  # calculated
    dict(name='עמלת בנק',                name_en='Bank fee',                   amount=22.0,   debit_day=5,    is_income=0, sort_order=13),
    dict(name='ביטוח בריאות',            name_en='Health insurance (Mutuelle)', amount=210.0,  debit_day=None, is_income=0, sort_order=14),
    dict(name='משיכת מזומן',             name_en='Cash withdrawal',            amount=None,   debit_day=None, is_income=0, sort_order=15),
]


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value REAL NOT NULL DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS expense_template (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL,
        name_en    TEXT,
        amount     REAL,
        debit_day  INTEGER,
        is_income  INTEGER DEFAULT 0,
        sort_order INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS current_expenses (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        template_id INTEGER,
        name        TEXT NOT NULL,
        name_en     TEXT,
        amount      REAL,
        debit_day   INTEGER,
        is_income   INTEGER DEFAULT 0,
        is_cleared  INTEGER DEFAULT 0,
        sort_order  INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS pending_transactions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL,
        amount     REAL NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # Default settings
    for key, value in [('balance', 0.0), ('future', 0.0),
                       ('savings_ignore', 8700.0), ('girls_money', 1000.0)]:
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

    # Populate template if empty
    if c.execute("SELECT COUNT(*) FROM expense_template").fetchone()[0] == 0:
        for item in EXPENSE_TEMPLATE:
            c.execute(
                "INSERT INTO expense_template (name, name_en, amount, debit_day, is_income, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (item['name'], item['name_en'], item['amount'],
                 item['debit_day'], item['is_income'], item['sort_order'])
            )

    conn.commit()
    conn.close()


def get_setting(key, default=0.0):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return float(row['value']) if row else default


def set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, float(value)))
    conn.commit()
    conn.close()


def compute_remaining(balance, future, savings_ignore, girls_money,
                      income_items, expense_items, pending_transactions):
    """Replicates the Excel formula: SUM(B2:B10) - SUM(B12:B32)"""
    income_sum  = sum(r['amount'] for r in income_items  if not r['is_cleared'] and r['amount'])
    expense_sum = sum(r['amount'] for r in expense_items if not r['is_cleared'] and r['amount'])
    pending_sum = sum(r['amount'] for r in pending_transactions)
    return balance + future + income_sum - expense_sum - pending_sum - savings_ignore - girls_money


# ---------------------------------------------------------------------------
# Ensure DB exists before first request
# ---------------------------------------------------------------------------

with app.app_context():
    if not os.path.exists(DATABASE):
        init_db()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    conn = get_db()
    income_items  = conn.execute(
        "SELECT * FROM current_expenses WHERE is_income=1 ORDER BY sort_order").fetchall()
    expense_items = conn.execute(
        "SELECT * FROM current_expenses WHERE is_income=0 ORDER BY sort_order").fetchall()
    pending_transactions = conn.execute(
        "SELECT * FROM pending_transactions ORDER BY created_at DESC").fetchall()
    conn.close()

    balance        = get_setting('balance')
    future         = get_setting('future')
    savings_ignore = get_setting('savings_ignore')
    girls_money    = get_setting('girls_money')

    remaining = compute_remaining(balance, future, savings_ignore, girls_money,
                                  income_items, expense_items, pending_transactions)
    days    = calculate_days_until_25()
    per_day = remaining / days if days > 0 else 0

    # Totals for display
    income_pending_total  = sum(r['amount'] for r in income_items  if not r['is_cleared'] and r['amount'])
    expense_pending_total = sum(r['amount'] for r in expense_items if not r['is_cleared'] and r['amount'])
    pending_total         = sum(r['amount'] for r in pending_transactions)

    today = date.today()
    is_reset_due = today.day >= 24  # highlight Reset button near the 25th

    return render_template('index.html',
        balance=balance, future=future,
        savings_ignore=savings_ignore, girls_money=girls_money,
        income_items=income_items, expense_items=expense_items,
        pending_transactions=pending_transactions,
        income_pending_total=income_pending_total,
        expense_pending_total=expense_pending_total,
        pending_total=pending_total,
        remaining=remaining, days=days, per_day=per_day,
        today=today, is_reset_due=is_reset_due,
    )


@app.route('/update-balance', methods=['POST'])
def update_balance():
    for key in ('balance', 'future'):
        val = request.form.get(key, '').strip()
        if val:
            set_setting(key, float(val))
    return redirect(url_for('index'))


@app.route('/clear-expense/<int:expense_id>', methods=['POST'])
def clear_expense(expense_id):
    conn = get_db()
    conn.execute("UPDATE current_expenses SET is_cleared=1 WHERE id=?", (expense_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))


@app.route('/unclear-expense/<int:expense_id>', methods=['POST'])
def unclear_expense(expense_id):
    conn = get_db()
    conn.execute("UPDATE current_expenses SET is_cleared=0 WHERE id=?", (expense_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))


@app.route('/add-pending', methods=['POST'])
def add_pending():
    name   = request.form.get('name', '').strip()
    amount = request.form.get('amount', '').strip()
    if name and amount:
        try:
            conn = get_db()
            conn.execute("INSERT INTO pending_transactions (name, amount) VALUES (?, ?)",
                         (name, float(amount)))
            conn.commit()
            conn.close()
        except ValueError:
            pass
    return redirect(url_for('index'))


@app.route('/delete-pending/<int:pending_id>', methods=['POST'])
def delete_pending(pending_id):
    conn = get_db()
    conn.execute("DELETE FROM pending_transactions WHERE id=?", (pending_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))


@app.route('/month-reset', methods=['GET', 'POST'])
def month_reset():
    today = date.today()

    if request.method == 'POST':
        food_cost = calculate_girls_food(today.year, today.month)
        conn = get_db()

        conn.execute("DELETE FROM current_expenses")
        if request.form.get('clear_pending'):
            conn.execute("DELETE FROM pending_transactions")

        templates = conn.execute(
            "SELECT * FROM expense_template ORDER BY sort_order").fetchall()

        for t in templates:
            amount = t['amount']
            if t['name'] == 'אוכל בנות':
                amount = food_cost  # override with calculated value

            conn.execute(
                "INSERT INTO current_expenses "
                "(template_id, name, name_en, amount, debit_day, is_income, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (t['id'], t['name'], t['name_en'], amount,
                 t['debit_day'], t['is_income'], t['sort_order'])
            )

        conn.commit()
        conn.close()

        flash(f'Month reset for {today.strftime("%B %Y")} complete! '
              f"Girls' food: €{food_cost:.2f}", 'success')
        return redirect(url_for('index'))

    # GET — show preview before confirming
    food_cost = calculate_girls_food(today.year, today.month)
    conn = get_db()
    templates = conn.execute("SELECT * FROM expense_template ORDER BY sort_order").fetchall()
    conn.close()

    return render_template('month_reset.html',
        today=today, food_cost=food_cost, templates=templates)


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        for key in ('savings_ignore', 'girls_money'):
            val = request.form.get(key, '').strip()
            if val:
                set_setting(key, float(val))

        conn = get_db()
        for key, value in request.form.items():
            if key.startswith('amount_'):
                tid = int(key.split('_')[1])
                conn.execute("UPDATE expense_template SET amount=? WHERE id=?",
                             (float(value) if value.strip() else None, tid))
            elif key.startswith('day_'):
                tid = int(key.split('_')[1])
                conn.execute("UPDATE expense_template SET debit_day=? WHERE id=?",
                             (int(value) if value.strip() else None, tid))
        conn.commit()
        conn.close()

        flash('Settings saved!', 'success')
        return redirect(url_for('settings'))

    conn = get_db()
    templates = conn.execute("SELECT * FROM expense_template ORDER BY sort_order").fetchall()
    conn.close()

    return render_template('settings.html',
        templates=templates,
        savings_ignore=get_setting('savings_ignore'),
        girls_money=get_setting('girls_money'),
    )


if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        init_db()
    app.run(debug=True)
