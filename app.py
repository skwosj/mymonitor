from flask import Flask, render_template, request, jsonify
from database import init_db, get_db, encrypt_password, decrypt_password
from collector import collect_metrics
from apscheduler.schedulers.background import BackgroundScheduler
import threading, time

app = Flask(__name__)
scheduler = BackgroundScheduler()
prev_net = {}

def do_collect(host_id):
    db = get_db()
    host = db.execute('SELECT * FROM hosts WHERE id=?', (host_id,)).fetchone()
    if not host:
        db.close(); return
    try:
        h = dict(host)
        h['password'] = decrypt_password(h['password'])
        data = collect_metrics(h)
        global prev_net
        pid = str(host_id)
        if pid in prev_net:
            data['net_speed_down'] = max(0, (data['net_bytes_rx'] - prev_net[pid]['rx']) / 10 / 1024 / 1024)
            data['net_speed_up'] = max(0, (data['net_bytes_tx'] - prev_net[pid]['tx']) / 10 / 1024 / 1024)
        prev_net[pid] = {'rx': data['net_bytes_rx'], 'tx': data['net_bytes_tx']}
        db.execute('''INSERT INTO metrics (host_id,cpu_usage,mem_total,mem_used,mem_usage,
            disk_total,disk_used,disk_usage,net_speed_down,net_speed_up,load_avg,uptime)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (host_id, data['cpu_usage'], data['mem_total'], data['mem_used'],
             data['mem_usage'], data['disk_total'], data['disk_used'], data['disk_usage'],
             data['net_speed_down'], data['net_speed_up'], data['load_avg'], data['uptime']))
        old_status = host['status']
        db.execute('UPDATE hosts SET status=? WHERE id=?', ('online', host_id))
        if old_status != 'online':
            db.execute('INSERT INTO status_changes (host_id,old_status,new_status) VALUES (?,?,?)',
                (host_id, old_status, 'online'))
        for atype, val, thresh in [
            ('cpu', data['cpu_usage'], host['cpu_threshold']),
            ('memory', data['mem_usage'], host['mem_threshold']),
            ('disk', data['disk_usage'], host['disk_threshold'])]:
            if val > thresh:
                db.execute('INSERT INTO alerts (host_id,alert_type,current_value,threshold) VALUES (?,?,?,?)',
                    (host_id, atype, val, thresh))
        db.commit()
    except:
        old_status = host['status']
        db.execute('UPDATE hosts SET status=? WHERE id=?', ('offline', host_id))
        if old_status != 'offline':
            db.execute('INSERT INTO status_changes (host_id,old_status,new_status) VALUES (?,?,?)',
                (host_id, old_status, 'offline'))
        db.commit()
    db.close()

def collect_all():
    db = get_db()
    hosts = db.execute('SELECT id FROM hosts').fetchall()
    db.close()
    for h in hosts:
        threading.Thread(target=do_collect, args=(h['id'],), daemon=True).start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/hosts', methods=['GET'])
def get_hosts():
    db = get_db()
    hosts = db.execute('''SELECT h.*, m.cpu_usage, m.mem_usage, m.disk_usage,
        m.net_speed_down, m.net_speed_up, m.timestamp as last_update
        FROM hosts h LEFT JOIN metrics m ON h.id=m.host_id
        WHERE m.id=(SELECT MAX(id) FROM metrics WHERE host_id=h.id) OR m.id IS NULL
        ORDER BY h.ip''').fetchall()
    db.close()
    result = []
    for h in hosts:
        d = dict(h)
        d.pop('password', None)
        result.append(d)
    return jsonify(result)

@app.route('/api/hosts', methods=['POST'])
def add_host():
    d = request.json
    db = get_db()
    try:
        db.execute('''INSERT INTO hosts (ip,port,username,password,description,group_name,
            cpu_threshold,mem_threshold,disk_threshold) VALUES (?,?,?,?,?,?,?,?,?)''',
            (d['ip'], d.get('port',22), d['username'], encrypt_password(d['password']),
             d.get('description',''), d.get('group','默认分组'),
             d.get('cpu_threshold',80), d.get('mem_threshold',85), d.get('disk_threshold',90)))
        db.commit()
        host_id = db.execute('SELECT id FROM hosts WHERE ip=?', (d['ip'],)).fetchone()['id']
        db.close()
        threading.Thread(target=do_collect, args=(host_id,), daemon=True).start()
        return jsonify({'success': True})
    except Exception as e:
        db.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/hosts/<int:hid>', methods=['PUT'])
def update_host(hid):
    d = request.json
    db = get_db()
    try:
        old = db.execute('SELECT * FROM hosts WHERE id=?', (hid,)).fetchone()
        if not old:
            db.close()
            return jsonify({'success': False, 'error': '主机不存在'})
        if d.get('password'):
            pwd = encrypt_password(d['password'])
        else:
            pwd = old['password']
        db.execute('''UPDATE hosts SET port=?,username=?,password=?,description=?,
            group_name=?,cpu_threshold=?,mem_threshold=?,disk_threshold=? WHERE id=?''',
            (d.get('port',22), d.get('username',old['username']), pwd,
             d.get('description',''), d.get('group','默认分组'),
             d.get('cpu_threshold',80), d.get('mem_threshold',85),
             d.get('disk_threshold',90), hid))
        db.commit()
        db.close()
        threading.Thread(target=do_collect, args=(hid,), daemon=True).start()
        return jsonify({'success': True})
    except Exception as e:
        db.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/hosts/<int:hid>', methods=['DELETE'])
def del_host(hid):
    db = get_db()
    db.execute('DELETE FROM hosts WHERE id=?', (hid,))
    db.execute('DELETE FROM metrics WHERE host_id=?', (hid,))
    db.commit()
    db.close()
    return jsonify({'success': True})

@app.route('/api/metrics/<int:hid>')
def get_metrics(hid):
    hours = int(request.args.get('hours', 1))
    db = get_db()
    rows = db.execute('''SELECT * FROM metrics WHERE host_id=?
        AND timestamp >= datetime('now', ?)
        ORDER BY timestamp''', (hid, f'-{hours} hours')).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/alerts')
def get_alerts():
    db = get_db()
    rows = db.execute('''SELECT a.*, h.ip FROM alerts a JOIN hosts h ON a.host_id=h.id
        ORDER BY a.created_at DESC LIMIT 50''').fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/status_changes')
def get_status_changes():
    db = get_db()
    rows = db.execute('''SELECT s.*, h.ip FROM status_changes s JOIN hosts h ON s.host_id=h.id
        ORDER BY s.changed_at DESC LIMIT 50''').fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/overview')
def get_overview():
    db = get_db()
    hosts = db.execute('SELECT * FROM hosts').fetchall()
    online = sum(1 for h in hosts if h['status']=='online')
    metrics = db.execute('''SELECT AVG(m.cpu_usage) as avg_cpu, AVG(m.mem_usage) as avg_mem,
        AVG(m.disk_usage) as avg_disk, SUM(m.net_speed_down) as total_down, SUM(m.net_speed_up) as total_up
        FROM metrics m WHERE m.id IN (SELECT MAX(id) FROM metrics GROUP BY host_id)''').fetchone()
    alerts = db.execute('SELECT COUNT(*) as cnt FROM alerts WHERE created_at >= datetime("now","-1 hour")').fetchone()
    db.close()
    return jsonify({'total': len(hosts), 'online': online, 'metrics': dict(metrics), 'alert_count': alerts['cnt']})

if __name__ == '__main__':
    init_db()
    scheduler.add_job(collect_all, 'interval', seconds=10)
    scheduler.start()
    app.run(host='0.0.0.0', port=5000, debug=False)
