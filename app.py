import os
import sqlite3
from flask import Flask, request, jsonify, render_template, g, send_from_directory
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
DATABASE = os.path.join(os.path.dirname(__file__), 'heavy_equipment.db')


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    with app.app_context():
        db = get_db()
        db.executescript('''
            CREATE TABLE IF NOT EXISTS equipment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                model TEXT NOT NULL,
                name TEXT DEFAULT '',
                serial_number TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS daily_operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipment_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                operating_hours REAL DEFAULT 0,
                operating_distance REAL DEFAULT 0,
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE CASCADE,
                UNIQUE(equipment_id, date)
            );

            CREATE TABLE IF NOT EXISTS maintenance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipment_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                description TEXT NOT NULL,
                cost INTEGER DEFAULT 0,
                mechanic TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS fuel_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipment_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                unit_price INTEGER DEFAULT 0,
                total_cost INTEGER DEFAULT 0,
                station TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE CASCADE
            );
        ''')
        db.commit()


# ── Equipment ────────────────────────────────────────────────────────────────

@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('static', 'manifest.json')


@app.route('/sw.js')
def serve_sw():
    resp = send_from_directory('static', 'sw.js', mimetype='application/javascript')
    resp.headers['Service-Worker-Allowed'] = '/'
    return resp


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/equipment', methods=['GET'])
def get_equipment():
    db = get_db()
    rows = db.execute('SELECT * FROM equipment ORDER BY type, model, name').fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/equipment', methods=['POST'])
def add_equipment():
    data = request.get_json()
    if not data.get('type') or not data.get('model'):
        return jsonify({'error': '구분과 모델을 입력해주세요.'}), 400
    db = get_db()
    cur = db.execute(
        'INSERT INTO equipment (type, model, name, serial_number) VALUES (?, ?, ?, ?)',
        (data['type'].strip(), data['model'].strip(),
         data.get('name', '').strip(), data.get('serial_number', '').strip())
    )
    db.commit()
    return jsonify({'id': cur.lastrowid, 'message': '장비가 등록되었습니다.'})


@app.route('/api/equipment/<int:eq_id>', methods=['DELETE'])
def delete_equipment(eq_id):
    db = get_db()
    db.execute('PRAGMA foreign_keys = ON')
    db.execute('DELETE FROM equipment WHERE id = ?', (eq_id,))
    db.commit()
    return jsonify({'message': '장비가 삭제되었습니다.'})


# ── Daily Operations ─────────────────────────────────────────────────────────

@app.route('/api/equipment/<int:eq_id>/operations', methods=['GET'])
def get_operations(eq_id):
    db = get_db()
    start = request.args.get('start')
    end   = request.args.get('end')

    query  = 'SELECT * FROM daily_operations WHERE equipment_id = ?'
    params = [eq_id]
    if start:
        query += ' AND date >= ?'
        params.append(start)
    if end:
        query += ' AND date <= ?'
        params.append(end)
    query += ' ORDER BY date DESC'

    records = db.execute(query, params).fetchall()
    totals  = db.execute(
        'SELECT SUM(operating_hours) AS h, SUM(operating_distance) AS d '
        'FROM daily_operations WHERE equipment_id = ?', (eq_id,)
    ).fetchone()

    return jsonify({
        'records': [dict(r) for r in records],
        'cumulative': {
            'total_hours':    round(totals['h'] or 0, 1),
            'total_distance': round(totals['d'] or 0, 1),
        }
    })


@app.route('/api/equipment/<int:eq_id>/operations', methods=['POST'])
def save_operation(eq_id):
    data = request.get_json()
    if not data.get('date'):
        return jsonify({'error': '날짜를 입력해주세요.'}), 400
    db = get_db()
    db.execute(
        '''INSERT INTO daily_operations (equipment_id, date, operating_hours, operating_distance, notes)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(equipment_id, date) DO UPDATE SET
             operating_hours    = excluded.operating_hours,
             operating_distance = excluded.operating_distance,
             notes              = excluded.notes''',
        (eq_id, data['date'],
         float(data.get('operating_hours', 0)),
         float(data.get('operating_distance', 0)),
         data.get('notes', '').strip())
    )
    db.commit()
    return jsonify({'message': '가동 현황이 저장되었습니다.'})


@app.route('/api/equipment/<int:eq_id>/operations/<int:op_id>', methods=['DELETE'])
def delete_operation(eq_id, op_id):
    db = get_db()
    db.execute('DELETE FROM daily_operations WHERE id = ? AND equipment_id = ?', (op_id, eq_id))
    db.commit()
    return jsonify({'message': '삭제되었습니다.'})


# ── Maintenance ──────────────────────────────────────────────────────────────

@app.route('/api/equipment/<int:eq_id>/maintenance', methods=['GET'])
def get_maintenance(eq_id):
    db = get_db()
    records = db.execute(
        'SELECT * FROM maintenance WHERE equipment_id = ? ORDER BY date DESC', (eq_id,)
    ).fetchall()
    total = db.execute(
        'SELECT SUM(cost) AS t FROM maintenance WHERE equipment_id = ?', (eq_id,)
    ).fetchone()
    return jsonify({
        'records':    [dict(r) for r in records],
        'total_cost': total['t'] or 0,
    })


@app.route('/api/equipment/<int:eq_id>/maintenance', methods=['POST'])
def add_maintenance(eq_id):
    data = request.get_json()
    if not data.get('date') or not data.get('description'):
        return jsonify({'error': '날짜와 정비 내역을 입력해주세요.'}), 400
    db = get_db()
    cur = db.execute(
        'INSERT INTO maintenance (equipment_id, date, description, cost, mechanic, notes) VALUES (?, ?, ?, ?, ?, ?)',
        (eq_id, data['date'], data['description'].strip(),
         int(data.get('cost', 0)), data.get('mechanic', '').strip(), data.get('notes', '').strip())
    )
    db.commit()
    return jsonify({'id': cur.lastrowid, 'message': '정비 내역이 저장되었습니다.'})


@app.route('/api/equipment/<int:eq_id>/maintenance/<int:rec_id>', methods=['DELETE'])
def delete_maintenance(eq_id, rec_id):
    db = get_db()
    db.execute('DELETE FROM maintenance WHERE id = ? AND equipment_id = ?', (rec_id, eq_id))
    db.commit()
    return jsonify({'message': '삭제되었습니다.'})


# ── Fuel ─────────────────────────────────────────────────────────────────────

@app.route('/api/equipment/<int:eq_id>/fuel', methods=['GET'])
def get_fuel(eq_id):
    db = get_db()
    records = db.execute(
        'SELECT * FROM fuel_records WHERE equipment_id = ? ORDER BY date DESC', (eq_id,)
    ).fetchall()
    totals = db.execute(
        'SELECT SUM(amount) AS a, SUM(total_cost) AS c FROM fuel_records WHERE equipment_id = ?', (eq_id,)
    ).fetchone()
    return jsonify({
        'records':      [dict(r) for r in records],
        'total_amount': round(totals['a'] or 0, 1),
        'total_cost':   totals['c'] or 0,
    })


@app.route('/api/equipment/<int:eq_id>/fuel', methods=['POST'])
def add_fuel(eq_id):
    data = request.get_json()
    if not data.get('date') or not data.get('amount'):
        return jsonify({'error': '날짜와 주유량을 입력해주세요.'}), 400
    amount     = float(data['amount'])
    unit_price = int(data.get('unit_price', 0))
    total_cost = int(data.get('total_cost') or amount * unit_price)
    db = get_db()
    cur = db.execute(
        'INSERT INTO fuel_records (equipment_id, date, amount, unit_price, total_cost, station, notes) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (eq_id, data['date'], amount, unit_price, total_cost,
         data.get('station', '').strip(), data.get('notes', '').strip())
    )
    db.commit()
    return jsonify({'id': cur.lastrowid, 'message': '주유 내역이 저장되었습니다.'})


@app.route('/api/equipment/<int:eq_id>/fuel/<int:rec_id>', methods=['DELETE'])
def delete_fuel(eq_id, rec_id):
    db = get_db()
    db.execute('DELETE FROM fuel_records WHERE id = ? AND equipment_id = ?', (rec_id, eq_id))
    db.commit()
    return jsonify({'message': '삭제되었습니다.'})


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5001)
