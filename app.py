import os
import math
import sqlite3
from datetime import date
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session
from school_calendar import calculate_girls_food, calculate_days_until_25

# ---------------------------------------------------------------------------
# Database — SQLite in Codespace (dev), PostgreSQL on Render (production).
# Set DATABASE_URL env var to switch to PostgreSQL.
# ---------------------------------------------------------------------------
DATABASE_URL  = os.environ.get('DATABASE_URL', '')
DATABASE_PATH = os.environ.get('DATABASE_PATH', 'budget.db')
USE_POSTGRES  = bool(DATABASE_URL)


class DB:
    """Thin wrapper that gives sqlite3 and psycopg2 a unified interface."""

    def __init__(self):
        if USE_POSTGRES:
            import psycopg2
            import psycopg2.extras
            self._conn   = psycopg2.connect(DATABASE_URL,
                               cursor_factory=psycopg2.extras.RealDictCursor)
            self._cursor = self._conn.cursor()
        else:
            self._conn   = sqlite3.connect(DATABASE_PATH)
            self._conn.row_factory = sqlite3.Row
            self._cursor = None   # sqlite3 uses conn.execute() shorthand
        self._last = None

    def execute(self, sql, params=()):
        if USE_POSTGRES:
            sql = sql.replace('?', '%s')
            self._cursor.execute(sql, params)
            self._last = self._cursor
        else:
            self._last = self._conn.execute(sql, params)
        return self

    def fetchone(self):
        return self._last.fetchone() if self._last else None

    def fetchall(self):
        return self._last.fetchall() if self._last else []

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    # -- Helpers for INSERT OR REPLACE / INSERT OR IGNORE ----------------

    def upsert_setting(self, key, value):
        """Insert or update a row in the settings table."""
        if USE_POSTGRES:
            self.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, float(value))
            )
        else:
            self.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, float(value))
            )

    def insert_ignore_setting(self, key, value):
        """Insert a setting only if it doesn't already exist."""
        if USE_POSTGRES:
            self.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO NOTHING",
                (key, float(value))
            )
        else:
            self.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, float(value))
            )

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-me')

# ---------------------------------------------------------------------------
# Auth — password set via APP_PASSWORD env var.
# If not set (dev/Codespace), auth is skipped entirely.
# ---------------------------------------------------------------------------
APP_PASSWORD = os.environ.get('APP_PASSWORD', '')

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if APP_PASSWORD and not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == APP_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
        return render_template('login.html', error=True)
    return render_template('login.html', error=False)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))
# ---------------------------------------------------------------------------
# Template — mirrors Column C of the Excel sheet "מתגלגל"
# is_variable=1 → amount is entered manually at each month reset
# ---------------------------------------------------------------------------
EXPENSE_TEMPLATE = [
    # הכנסות
    dict(name='משכורת תום',               name_en="Tom's salary",               amount=None,   debit_day=None, is_income=1, is_variable=1, sort_order=1),
    dict(name='משכורת תמרי',              name_en="Tamari's salary",             amount=1200.0, debit_day=None, is_income=1, is_variable=0, sort_order=2),
    dict(name='CAF ילדים',                name_en='CAF children',                amount=150.0,  debit_day=None, is_income=1, is_variable=0, sort_order=3),
    dict(name='CAF דירה',                 name_en='CAF housing',                 amount=None,   debit_day=None, is_income=1, is_variable=1, sort_order=4),
    dict(name='לקבל חזרה מביטוח רפואי',  name_en='Medical insurance refund',    amount=None,   debit_day=None, is_income=1, is_variable=1, sort_order=5),
    dict(name='החזר מהעבודה',             name_en='Work reimbursement',          amount=None,   debit_day=None, is_income=1, is_variable=1, sort_order=6),
    # הוצאות
    dict(name='שכר דירה',                 name_en='Rent',                        amount=1683.0, debit_day=28,   is_income=0, is_variable=0, sort_order=7),
    dict(name='חשבון חשמל',              name_en='EDF',                         amount=151.0,  debit_day=16,   is_income=0, is_variable=1, sort_order=8),
    dict(name='נאביגו',                   name_en='Navigo',                      amount=230.0,  debit_day=6,    is_income=0, is_variable=1, sort_order=9),
    dict(name='טלפונים ואינטרנט',         name_en='Phones & internet',           amount=95.0,   debit_day=None, is_income=0, is_variable=0, sort_order=10),
    dict(name='ביטוח דירה',              name_en='Home insurance',              amount=13.0,   debit_day=19,   is_income=0, is_variable=0, sort_order=11),
    dict(name='אוכל בנות',               name_en="Girls' school food",          amount=None,   debit_day=5,    is_income=0, is_variable=0, sort_order=12),
    dict(name='עמלת בנק',                name_en='Bank fee',                    amount=22.0,   debit_day=5,    is_income=0, is_variable=0, sort_order=13),
    dict(name='ביטוח בריאות',            name_en='Mutuelle',                    amount=210.0,  debit_day=None, is_income=0, is_variable=0, sort_order=14),
    dict(name='משיכת מזומן',             name_en='Cash withdrawal',             amount=None,   debit_day=None, is_income=0, is_variable=1, sort_order=15),
]

SAVINGS_ITEMS = [
    dict(name='בתוך העו"ש', amount=8700.0,  sort_order=1),
    dict(name='פק"מ א',     amount=11728.0, sort_order=2),
    dict(name='פק"מ ב',     amount=13739.0, sort_order=3),
    dict(name='מניות',      amount=33570.0, sort_order=4),
]

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    return DB()


def get_setting(key, default=0.0):
    db = get_db()
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    db.close()
    return float(row['value']) if row else default


def set_setting(key, value):
    db = get_db()
    db.upsert_setting(key, value)
    db.commit()
    db.close()


def init_db():
    db = get_db()

    # Primary key syntax differs between SQLite and PostgreSQL
    PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

    db.execute(f'''CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value REAL NOT NULL DEFAULT 0
    )''')

    db.execute(f'''CREATE TABLE IF NOT EXISTS expense_template (
        id          {PK},
        name        TEXT NOT NULL,
        name_en     TEXT,
        amount      REAL,
        debit_day   INTEGER,
        is_income   INTEGER DEFAULT 0,
        is_variable INTEGER DEFAULT 0,
        sort_order  INTEGER DEFAULT 0
    )''')

    db.execute(f'''CREATE TABLE IF NOT EXISTS current_expenses (
        id          {PK},
        template_id INTEGER,
        name        TEXT NOT NULL,
        name_en     TEXT,
        amount      REAL,
        debit_day   INTEGER,
        is_income   INTEGER DEFAULT 0,
        is_variable INTEGER DEFAULT 0,
        is_cleared  INTEGER DEFAULT 0,
        sort_order  INTEGER DEFAULT 0
    )''')

    db.execute(f'''CREATE TABLE IF NOT EXISTS pending_transactions (
        id         {PK},
        name       TEXT NOT NULL,
        amount     REAL NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    db.execute(f'''CREATE TABLE IF NOT EXISTS savings (
        id         {PK},
        name       TEXT NOT NULL,
        amount     REAL DEFAULT 0,
        sort_order INTEGER DEFAULT 0
    )''')

    # Default settings
    for key, value in [
        ('balance', 0.0),
        ('future', 0.0),
        ('savings_ignore', 8700.0),
        ('savings_ignore_at_reset', 8700.0),
        ('girls_shachar', 500.0),
        ('girls_yaara', 500.0),
    ]:
        db.insert_ignore_setting(key, value)

    # Seed expense template if empty
    count = db.execute("SELECT COUNT(*) as n FROM expense_template").fetchone()
    if (count['n'] if USE_POSTGRES else count[0]) == 0:
        for item in EXPENSE_TEMPLATE:
            db.execute(
                "INSERT INTO expense_template "
                "(name, name_en, amount, debit_day, is_income, is_variable, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (item['name'], item['name_en'], item['amount'], item['debit_day'],
                 item['is_income'], item['is_variable'], item['sort_order'])
            )

    # Seed savings if empty
    count = db.execute("SELECT COUNT(*) as n FROM savings").fetchone()
    if (count['n'] if USE_POSTGRES else count[0]) == 0:
        for item in SAVINGS_ITEMS:
            db.execute(
                "INSERT INTO savings (name, amount, sort_order) VALUES (?, ?, ?)",
                (item['name'], item['amount'], item['sort_order'])
            )

    # Migrations (safe to run repeatedly)
    for col_sql in [
        "ALTER TABLE expense_template ADD COLUMN is_variable INTEGER DEFAULT 0",
        "ALTER TABLE current_expenses ADD COLUMN is_variable INTEGER DEFAULT 0",
    ]:
        try:
            db.execute(col_sql)
        except Exception:
            pass

    db.commit()
    db.close()


def compute_remaining(balance, future, savings_ignore, girls_total,
                      income_items, expense_items, pending_transactions):
    """Replicates Excel formula: SUM(B2:B10) - SUM(B12:B32)
    Conservative rounding: income floored, expenses ceiled, result floored.
    Girls' money deducted separately from savings_ignore."""
    income_sum  = sum(math.floor(r['amount']) for r in income_items  if not r['is_cleared'] and r['amount'])
    expense_sum = sum(math.ceil(r['amount'])  for r in expense_items if not r['is_cleared'] and r['amount'])
    pending_sum = sum(math.ceil(r['amount'])  for r in pending_transactions)
    raw = balance + future + income_sum - expense_sum - pending_sum - savings_ignore - girls_total
    return math.floor(raw)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

with app.app_context():
    init_db()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
@login_required
def index():
    conn = get_db()
    income_items         = conn.execute("SELECT * FROM current_expenses WHERE is_income=1 ORDER BY sort_order").fetchall()
    expense_items        = conn.execute("SELECT * FROM current_expenses WHERE is_income=0 ORDER BY sort_order").fetchall()
    pending_transactions = conn.execute("SELECT * FROM pending_transactions ORDER BY created_at DESC").fetchall()
    conn.close()

    balance                 = get_setting('balance')
    future                  = get_setting('future')
    savings_ignore          = get_setting('savings_ignore')
    savings_ignore_at_reset = get_setting('savings_ignore_at_reset')
    girls_shachar           = get_setting('girls_shachar')
    girls_yaara             = get_setting('girls_yaara')
    girls_total             = girls_shachar + girls_yaara

    remaining = compute_remaining(balance, future, savings_ignore, girls_total,
                                  income_items, expense_items, pending_transactions)
    days    = calculate_days_until_25()
    per_day = math.floor(remaining / days) if days > 0 else 0

    income_pending_total  = sum(r['amount'] for r in income_items  if not r['is_cleared'] and r['amount'])
    expense_pending_total = sum(r['amount'] for r in expense_items if not r['is_cleared'] and r['amount'])
    pending_total         = sum(r['amount'] for r in pending_transactions)

    today = date.today()

    return render_template('index.html',
        balance=balance, future=future,
        savings_ignore=savings_ignore,
        savings_ignore_at_reset=savings_ignore_at_reset,
        girls_shachar=girls_shachar, girls_yaara=girls_yaara, girls_total=girls_total,
        income_items=income_items, expense_items=expense_items,
        pending_transactions=pending_transactions,
        income_pending_total=income_pending_total,
        expense_pending_total=expense_pending_total,
        pending_total=pending_total,
        remaining=remaining, days=days, per_day=per_day,
        today=today, is_reset_due=(today.day >= 24),
    )


@app.route('/update-balance', methods=['POST'])
@login_required
def update_balance():
    for key in ('balance', 'future', 'savings_ignore'):
        val = request.form.get(key, '').strip()
        if val:
            set_setting(key, float(val))
    return redirect(url_for('index'))


@app.route('/clear-expense/<int:expense_id>', methods=['POST'])
@login_required
def clear_expense(expense_id):
    conn = get_db()
    conn.execute("UPDATE current_expenses SET is_cleared=1 WHERE id=?", (expense_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))


@app.route('/unclear-expense/<int:expense_id>', methods=['POST'])
@login_required
def unclear_expense(expense_id):
    conn = get_db()
    conn.execute("UPDATE current_expenses SET is_cleared=0 WHERE id=?", (expense_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))


@app.route('/update-expense-amount/<int:expense_id>', methods=['POST'])
@login_required
def update_expense_amount(expense_id):
    val = request.form.get('amount', '').strip()
    if val:
        try:
            conn = get_db()
            conn.execute("UPDATE current_expenses SET amount=? WHERE id=?",
                         (float(val), expense_id))
            conn.commit()
            conn.close()
        except ValueError:
            pass
    return redirect(url_for('index'))


@app.route('/pending')
@login_required
def pending_mobile():
    conn = get_db()
    pending_transactions = conn.execute(
        "SELECT * FROM pending_transactions ORDER BY created_at DESC").fetchall()
    conn.close()
    total = sum(r['amount'] for r in pending_transactions)
    return render_template('pending_mobile.html',
        pending_transactions=pending_transactions, total=total)


@app.route('/add-pending', methods=['POST'])
@login_required
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
@login_required
def delete_pending(pending_id):
    conn = get_db()
    conn.execute("DELETE FROM pending_transactions WHERE id=?", (pending_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))


@app.route('/month-reset', methods=['GET', 'POST'])
@login_required
def month_reset():
    today = date.today()

    if request.method == 'POST':
        food_cost = calculate_girls_food(today.year, today.month)
        conn = get_db()

        conn.execute("DELETE FROM current_expenses")
        if request.form.get('clear_pending'):
            conn.execute("DELETE FROM pending_transactions")

        # Freeze savings_ignore at the time of reset
        current_savings_ignore = get_setting('savings_ignore')
        set_setting('savings_ignore_at_reset', current_savings_ignore)

        templates = conn.execute("SELECT * FROM expense_template ORDER BY sort_order").fetchall()
        for t in templates:
            amount = t['amount']
            if t['name'] == 'אוכל בנות':
                amount = food_cost
            elif t['is_variable']:
                # Use manually entered value from reset form
                val = request.form.get(f'var_{t["id"]}', '').strip()
                if val:
                    amount = float(val)

            conn.execute(
                "INSERT INTO current_expenses "
                "(template_id, name, name_en, amount, debit_day, is_income, is_variable, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (t['id'], t['name'], t['name_en'], amount,
                 t['debit_day'], t['is_income'], t['is_variable'], t['sort_order'])
            )

        conn.commit()
        conn.close()

        flash(f'Month reset for {today.strftime("%B %Y")} complete! '
              f"Girls' food: \u20ac{food_cost:.2f}", 'success')
        return redirect(url_for('index'))

    food_cost = calculate_girls_food(today.year, today.month)
    conn = get_db()
    templates = conn.execute("SELECT * FROM expense_template ORDER BY sort_order").fetchall()
    conn.close()

    return render_template('month_reset.html',
        today=today, food_cost=food_cost, templates=templates)


@app.route('/savings', methods=['GET', 'POST'])
@login_required
def savings():
    if request.method == 'POST':
        conn = get_db()
        for key, value in request.form.items():
            if key.startswith('saving_'):
                sid    = int(key.split('_')[1])
                val    = value.strip()
                amount = float(val) if val else 0.0
                conn.execute("UPDATE savings SET amount=? WHERE id=?", (amount, sid))
                row = conn.execute("SELECT name FROM savings WHERE id=?", (sid,)).fetchone()
                if row and row['name'] == 'בתוך העו"ש':
                    conn.upsert_setting('savings_ignore', amount)
        for key in ('girls_shachar', 'girls_yaara'):
            val = request.form.get(key, '').strip()
            if val:
                conn.upsert_setting(key, float(val))
        conn.commit()
        conn.close()
        flash('Savings updated!', 'success')
        return redirect(url_for('savings'))

    conn = get_db()
    savings_items = conn.execute("SELECT * FROM savings ORDER BY sort_order").fetchall()
    conn.close()

    return render_template('savings.html',
        savings_items=savings_items,
        savings_total=sum(s['amount'] for s in savings_items),
        girls_shachar=get_setting('girls_shachar'),
        girls_yaara=get_setting('girls_yaara'),
    )


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        conn = get_db()
        for key, value in request.form.items():
            if key.startswith('amount_'):
                tid = int(key.split('_')[1])
                val = value.strip()
                conn.execute("UPDATE expense_template SET amount=? WHERE id=?",
                             (float(val) if val else None, tid))
            elif key.startswith('day_'):
                tid = int(key.split('_')[1])
                val = value.strip()
                conn.execute("UPDATE expense_template SET debit_day=? WHERE id=?",
                             (int(val) if val else None, tid))
            elif key.startswith('variable_'):
                tid = int(key.split('_')[1])
                conn.execute("UPDATE expense_template SET is_variable=1 WHERE id=?", (tid,))
        # Unset is_variable for unchecked boxes
        all_tids = [row['id'] for row in conn.execute("SELECT id FROM expense_template").fetchall()]
        checked  = {int(k.split('_')[1]) for k in request.form if k.startswith('variable_')}
        for tid in all_tids:
            if tid not in checked:
                conn.execute("UPDATE expense_template SET is_variable=0 WHERE id=?", (tid,))
        conn.commit()
        conn.close()
        flash('Settings saved!', 'success')
        return redirect(url_for('settings'))

    conn = get_db()
    templates = conn.execute("SELECT * FROM expense_template ORDER BY sort_order").fetchall()
    conn.close()
    return render_template('settings.html', templates=templates)


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
