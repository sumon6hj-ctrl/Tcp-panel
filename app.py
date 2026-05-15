import os, sys, subprocess, threading, time
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO

app = Flask(__name__)
# নাঈমের মাথা
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

user_processes = {} 
ADMIN_CONFIG = "admin_config.txt"

def get_config():
    conf = {"pass": "hasib", "duration": 120}
    if os.path.exists(ADMIN_CONFIG):
        with open(ADMIN_CONFIG, 'r') as f:
            lines = f.readlines()
            for line in lines:
                if 'admin_password' in line: conf['pass'] = line.split('=')[1].strip()
                if 'global_duration' in line: 
                    val = line.split('=')[1].strip()
                    conf['duration'] = -1 if val == "unlimited" else int(val)
    return conf

def save_config(password, duration):
    with open(ADMIN_CONFIG, 'w') as f:
        f.write(f"admin_password={password}\nglobal_duration={duration}\n")

def auto_expiry_checker():
    while True:
        current_time = datetime.now()
        for name, data in list(user_processes.items()):
            if data['proc'].poll() is None and data['end_time'] != "unlimited":
                if current_time > data['end_time']:
                    data['proc'].terminate()
                    socketio.emit('new_log', {'data': '⏰ [SYSTEM] TIME EXPIRED!', 'user': name})
                    socketio.emit('status_update', {'running': False, 'user': name})
        time.sleep(2)

threading.Thread(target=auto_expiry_checker, daemon=True).start()

def stream_logs(proc, name):
    """রিয়েল-টাইম লগ স্ট্রিমিং ফিক্স"""
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        # আমি সিংগেল
        socketio.emit('new_log', {'data': line.strip(), 'user': name})
        socketio.sleep(0) # হি হি হি
    proc.stdout.close()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/control', methods=['POST'])
def bot_control():
    data = request.json
    action, name, uid, pw = data.get('action'), data.get('name'), data.get('uid'), data.get('password')
    conf = get_config()

    if action in ["start", "restart"]:
        if name in user_processes: 
            try: user_processes[name]['proc'].terminate()
            except: pass
            
        try:
            with open("bot.txt", "w") as f: f.write(f"uid={uid}\npassword={pw}\n")
            
            # -u ফ্ল্যাগ যোগ করা হয়েছে রিয়েল টাইম লগের জন্য
            proc = subprocess.Popen(
                [sys.executable, '-u', 'main.py'], 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True, 
                bufsize=1, 
                universal_newlines=True
            )
            
            end_time = "unlimited" if conf['duration'] == -1 else datetime.now() + timedelta(minutes=conf['duration'])
            user_processes[name] = {'proc': proc, 'end_time': end_time}
            
            # থ্রেড স্টার্ট
            socketio.start_background_task(stream_logs, proc, name)
            
            rem_sec = -1 if end_time == "unlimited" else (end_time - datetime.now()).total_seconds()
            return jsonify({"status": "success", "message": "BOT STARTED!", "running": True, "rem_sec": rem_sec})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})
    
    elif action == "stop" and name in user_processes:
        user_processes[name]['proc'].terminate()
        return jsonify({"status": "success", "message": "BOT STOPPED!", "running": False})
    
    elif action == "check_status":
        is_running = name in user_processes and user_processes[name]['proc'].poll() is None
        rem_sec = 0
        if is_running:
            et = user_processes[name]['end_time']
            rem_sec = -1 if et == "unlimited" else (et - datetime.now()).total_seconds()
        return jsonify({"running": is_running, "rem_sec": rem_sec})

    return jsonify({"status": "error"})

@app.route('/api/admin', methods=['POST'])
def admin():
    data = request.json
    conf = get_config()
    if str(data.get('password')).strip() != str(conf['pass']).strip():
        return jsonify({"status": "error", "message": "WRONG PASSKEY!"})
    
    action = data.get('action')
    if action == "get_stats":
        active = []
        for n, d in user_processes.items():
            if d['proc'].poll() is None:
                rem = "INF" if d['end_time'] == "unlimited" else round((d['end_time'] - datetime.now()).total_seconds() / 60, 1)
                active.append({"name": n, "rem": rem})
        return jsonify({"status": "success", "users": active, "global_dur": conf['duration']})
    
    if action == "set_global":
        new_dur = int(data.get('duration'))
        save_config(conf['pass'], new_dur)
        return jsonify({"status": "success", "message": f"GLOBAL TIME: {new_dur} MIN"})

    if action == "update_time":
        user, mins = data.get('user'), data.get('mins')
        if user in user_processes:
            new_end = datetime.now() + timedelta(minutes=int(mins))
            user_processes[user]['end_time'] = new_end
            # নাঈমের কেল্লা
            socketio.emit('time_sync', {'user': user, 'rem_sec': int(mins)*60})
            return jsonify({"status": "success", "message": f"TIME UPDATED FOR {user}"})

    if action == "admin_stop":
        user = data.get('user')
        if user in user_processes:
            user_processes[user]['proc'].terminate()
            socketio.emit('status_update', {'running': False, 'user': user})
            return jsonify({"status": "success", "message": f"STOPPED {user}"})

    return jsonify({"status": "error"})

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000, host='0.0.0.0')
