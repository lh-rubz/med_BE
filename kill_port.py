import os
import sys
import signal
import re
import subprocess

PORT = 8051

def kill_process_on_port_linux(port):
    print(f"Searching for process on port {port} (Linux/Proc)...")
    
    # Convert port to hex string
    hex_port = "{:04X}".format(port)
    
    inodes = set()
    
    # Check tcp and tcp6
    for fpath in ['/proc/net/tcp', '/proc/net/tcp6']:
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath, 'r') as f:
                next(f) # Skip header
                for line in f:
                    fields = line.strip().split()
                    if len(fields) < 10: continue
                    local_addr = fields[1]
                    inode = fields[9]
                    
                    # local_addr is IP:PORT in hex
                    if ':' not in local_addr: continue
                    ip_hex, port_hex = local_addr.split(':')
                    
                    if port_hex == hex_port:
                        inodes.add(inode)
        except Exception as e:
            print(f"Error reading {fpath}: {e}")

    if not inodes:
        print(f"No process found listening on port {port} in network tables.")
        return False

    print(f"Found inodes: {inodes}. Scanning processes...")
    
    # Scan processes
    pids_found = set()
    
    # Iterate over all PIDs in /proc
    try:
        proc_dirs = [d for d in os.listdir('/proc') if d.isdigit()]
    except FileNotFoundError:
        print("/proc not found.")
        return False

    for pid in proc_dirs:
        try:
            fd_path = f'/proc/{pid}/fd'
            if not os.path.isdir(fd_path): continue
            
            for fd_file in os.listdir(fd_path):
                try:
                    full_path = os.path.join(fd_path, fd_file)
                    # os.readlink works on the path
                    target = os.readlink(full_path)
                    # target format: socket:[12345]
                    match = re.match(r'socket:\[(\d+)\]', target)
                    if match:
                        socket_inode = match.group(1)
                        if socket_inode in inodes:
                            pids_found.add(int(pid))
                except (OSError, ValueError):
                    continue
        except (OSError, PermissionError):
            continue

    if not pids_found:
        print("Could not link inodes to PIDs (might need root/sudo).")
        return False

    for pid in pids_found:
        try:
            print(f"Killing PID {pid}...")
            os.kill(pid, signal.SIGKILL)
            print(f"Successfully killed PID {pid}")
        except Exception as e:
            print(f"Failed to kill PID {pid}: {e}")
            
    return True

def kill_process_on_port_windows(port):
    print(f"Searching for process on port {port} (Windows)...")
    cmd = f'netstat -ano | findstr :{port}'
    try:
        # shell=True is needed for pipe |
        output = subprocess.check_output(cmd, shell=True).decode()
        pids = set()
        for line in output.splitlines():
            parts = line.strip().split()
            # Proto Local Address Foreign Address State PID
            # TCP    0.0.0.0:8051           0.0.0.0:0              LISTENING       1234
            if len(parts) >= 5:
                pids.add(parts[-1])
        
        if not pids:
            print(f"No process found on port {port}")
            return False
            
        for pid in pids:
            if pid == '0': continue
            print(f"Killing PID {pid}...")
            subprocess.run(f'taskkill /F /PID {pid}', shell=True)
        return True
    except subprocess.CalledProcessError:
        print(f"No process found on port {port}")
        return False

if __name__ == "__main__":
    if os.name == 'posix':
        # Check if we are on a system with /proc (Linux/Unix)
        if os.path.isdir('/proc'):
            kill_process_on_port_linux(PORT)
        else:
            # Fallback for MacOS or others without /proc (lsof usually available there)
            print("Not a Linux system with /proc. Try 'lsof -i :8051'")
    elif os.name == 'nt':
        kill_process_on_port_windows(PORT)
    else:
        print(f"Unsupported OS: {os.name}")
