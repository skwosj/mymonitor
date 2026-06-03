import paramiko
import re

def collect_metrics(host):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(host['ip'], port=host['port'],
                    username=host['username'],
                    password=host['password'], timeout=10)
        def run(cmd):
            _, out, _ = ssh.exec_command(cmd)
            return out.read().decode().strip()

        cpu = float(run("top -bn1 | grep 'Cpu(s)' | awk '{print $2}'").replace(',','.') or 0)
        mem = run("free -m | grep Mem")
        mem_parts = mem.split()
        mem_total = int(mem_parts[1])
        mem_used = int(mem_parts[2])
        mem_usage = round(mem_used / mem_total * 100, 1)

        disk = run("df / | tail -1")
        disk_parts = disk.split()
        disk_total = int(disk_parts[1]) // 1024
        disk_used = int(disk_parts[2]) // 1024
        disk_usage = float(disk_parts[4].replace('%',''))

        net = run("cat /proc/net/dev | grep -E 'eth0|ens|enp' | head -1")
        net_parts = net.split()
        rx = int(net_parts[1]) if len(net_parts) > 1 else 0
        tx = int(net_parts[9]) if len(net_parts) > 9 else 0

        load = run("cat /proc/loadavg | awk '{print $1,$2,$3}'")
        uptime = run("uptime -p")

        ssh.close()
        return {
            'cpu_usage': cpu,
            'mem_total': mem_total,
            'mem_used': mem_used,
            'mem_usage': mem_usage,
            'disk_total': disk_total,
            'disk_used': disk_used,
            'disk_usage': disk_usage,
            'net_bytes_rx': rx,
            'net_bytes_tx': tx,
            'net_speed_down': 0,
            'net_speed_up': 0,
            'load_avg': load,
            'uptime': uptime
        }
    except Exception as e:
        if ssh: ssh.close()
        raise e
