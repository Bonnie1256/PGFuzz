#!/usr/bin/env python3
"""
Terminal window management module for automation scripts.
Handles opening terminals and properly closing them.
"""

import subprocess
import time
import os
import sys

class TerminalManager:
    def __init__(self):
        self.terminal_process = None
        self.terminal_window_id = None
    
    def open_terminal(self, command):
        """Open a terminal with the given command"""
        try:
            # Open terminal with the command
            cmd = f'gnome-terminal -- {command} &'
            self.terminal_process = subprocess.Popen(cmd, shell=True)
            print(f"Terminal opened with PID: {self.terminal_process.pid}")
            
            # Wait a moment for the terminal to appear
            time.sleep(2)
            
            # Find the terminal window
            self.terminal_window_id = self._find_terminal_window()
            if self.terminal_window_id:
                print(f"Found terminal window ID: {self.terminal_window_id}")
                return True
            else:
                print("Warning: Could not find terminal window ID")
                return True  # Still return True as the process is running
                
        except Exception as e:
            print(f"Error opening terminal: {e}")
            return False
    
    def _find_terminal_window(self):
        """Find the terminal window ID"""
        try:
            # Get all terminal windows
            result = subprocess.run(['wmctrl', '-l'], capture_output=True, text=True)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                # Look for the most recent terminal window
                for line in reversed(lines):  # Check from newest to oldest
                    if 'gnome-terminal' in line.lower() or 'terminal' in line.lower():
                        # Extract window ID (first part of the line)
                        parts = line.split()
                        if parts:
                            window_id = parts[0]
                            # Verify this window is still active
                            try:
                                verify_result = subprocess.run(['wmctrl', '-i', '-G', window_id], 
                                                           capture_output=True, text=True, timeout=2)
                                if verify_result.returncode == 0:
                                    return window_id
                            except:
                                continue
            return None
        except Exception as e:
            print(f"Error finding terminal window: {e}")
            return None
    
    def close_terminal(self):
        """Close the terminal window and all its subprocesses"""
        success = True
        
        # Method 1: Send Ctrl+C to the terminal to gracefully stop processes
        if self.terminal_window_id:
            try:
                # Focus the window and send Ctrl+C
                subprocess.run(['xdotool', 'windowactivate', self.terminal_window_id], 
                             capture_output=True, timeout=2)
                time.sleep(0.5)
                subprocess.run(['xdotool', 'key', 'ctrl+c'], 
                             capture_output=True, timeout=2)
                print("Sent Ctrl+C to terminal")
                time.sleep(2)  # Give processes time to terminate gracefully
            except Exception as e:
                print(f"Error sending Ctrl+C: {e}")
        
        # Method 2: Close the window using wmctrl
        if self.terminal_window_id:
            try:
                result = subprocess.run(['wmctrl', '-i', '-c', self.terminal_window_id], 
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"✓ Terminal window {self.terminal_window_id} closed")
                else:
                    print(f"✗ Failed to close window {self.terminal_window_id}")
                    success = False
            except Exception as e:
                print(f"Error closing window: {e}")
                success = False
        
        # Method 3: Terminate the process and its children
        if self.terminal_process:
            try:
                if self.terminal_process.poll() is None:  # Process is still running
                    # First try graceful termination
                    self.terminal_process.terminate()
                    try:
                        self.terminal_process.wait(timeout=5)
                        print("✓ Terminal process terminated gracefully")
                    except subprocess.TimeoutExpired:
                        # If graceful termination fails, kill the process group
                        try:
                            import os
                            import signal
                            os.killpg(os.getpgid(self.terminal_process.pid), signal.SIGTERM)
                            print("✓ Terminal process group terminated")
                        except:
                            # Last resort: force kill
                            self.terminal_process.kill()
                            print("✓ Terminal process force killed")
            except Exception as e:
                print(f"Error terminating process: {e}")
                success = False
        
        # Method 4: Clean up any remaining processes
        try:
            # Kill any remaining python processes that might be related
            subprocess.run(['pkill', '-f', 'open_simulator.py'], 
                         capture_output=True, timeout=5)
            subprocess.run(['pkill', '-f', 'sim_vehicle.py'], 
                         capture_output=True, timeout=5)
            print("✓ Cleaned up remaining processes")
        except Exception as e:
            print(f"Warning: Error cleaning up remaining processes: {e}")
        
        return success
    
    def is_terminal_running(self):
        """Check if the terminal is still running"""
        if self.terminal_process:
            return self.terminal_process.poll() is None
        return False
    
    def reset(self):
        """Reset the terminal manager state for next use"""
        self.terminal_process = None
        self.terminal_window_id = None

def test_terminal_manager():
    """Test the terminal manager"""
    print("=== Testing Terminal Manager ===")
    
    manager = TerminalManager()
    
    # Test opening a terminal
    print("1. Opening test terminal...")
    success = manager.open_terminal('python -c "import time; print(\'Test running\'); time.sleep(10); print(\'Test done\')"')
    
    if success:
        print("2. Terminal opened successfully")
        
        # Wait a bit
        print("3. Waiting 3 seconds...")
        time.sleep(3)
        
        # Check if running
        if manager.is_terminal_running():
            print("4. Terminal is still running")
        else:
            print("4. Terminal has finished")
        
        # Close the terminal
        print("5. Closing terminal...")
        manager.close_terminal()
        
        # Final check
        if manager.is_terminal_running():
            print("6. Terminal is still running (cleanup failed)")
        else:
            print("6. Terminal closed successfully")
    else:
        print("Failed to open terminal")

if __name__ == "__main__":
    test_terminal_manager()
