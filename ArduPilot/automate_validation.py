#!/usr/bin/env python3
"""
Automation script for validating all policy violation files.
This script automates the process of:
1. Starting the simulator in a separate terminal
2. Running fuzzing_validation.py for each file
3. Cleaning up processes between iterations
"""

import os
import sys
import time
import signal
import subprocess
import glob
from pathlib import Path
from terminal_manager import TerminalManager

class ValidationAutomator:
    def __init__(self, policy_violations_dir="policy_violations"):
        self.policy_violations_dir = policy_violations_dir
        self.terminal_manager = TerminalManager()
        self.validation_process = None
        self.total_files = 0
        self.processed_files = 0
        self.skipped_files = 0
        self.cleanup_done = False
        
    def get_all_files(self, start_from=None):
        """Get all .txt files in the policy_violations directory"""
        pattern = os.path.join(self.policy_violations_dir, "*.txt")
        files = glob.glob(pattern)
        files.sort()  # Sort for consistent ordering
        
        if start_from:
            # Find the starting file and slice the list
            print(f"Looking for starting file: {start_from}")
            print(f"First few files in list: {[os.path.basename(f) for f in files[:5]]}")
            
            try:
                # Handle both full path and just filename
                if os.path.basename(start_from) == start_from:
                    # Just filename provided, look for it in the files list
                    start_index = next(i for i, f in enumerate(files) if os.path.basename(f) == start_from)
                else:
                    # Full path provided
                    start_index = files.index(start_from)
                
                files = files[start_index:]
                print(f"✓ Found starting file! Resuming from: {os.path.basename(files[0]) if files else 'none'}")
            except (ValueError, StopIteration):
                print(f"✗ Warning: Starting file '{start_from}' not found in file list")
                print(f"Available files around that range:")
                # Show files around the expected position
                for i, f in enumerate(files):
                    if '368' in os.path.basename(f) or '367' in os.path.basename(f) or '369' in os.path.basename(f):
                        print(f"  {i}: {os.path.basename(f)}")
                print("Starting from beginning...")
        
        return files
    
    def is_file_empty(self, filepath):
        """Check if a file is empty or contains only whitespace"""
        try:
            with open(filepath, 'r') as f:
                content = f.read().strip()
                return len(content) == 0
        except Exception as e:
            print(f"Error reading file {filepath}: {e}")
            return True  # Skip files that can't be read
    
    def start_simulator(self):
        """Start the simulator process in a separate terminal"""
        try:
            print("Starting simulator in separate terminal...")
            # Use terminal manager to open simulator
            success = self.terminal_manager.open_terminal(f'python {os.path.abspath("open_simulator.py")}')
            if success:
                print("Simulator started, waiting 60 seconds for initialization...")
                time.sleep(60)
                return True
            else:
                print("Failed to start simulator")
                return False
        except Exception as e:
            print(f"Failed to start simulator: {e}")
            return False
    
    def run_validation(self, filepath):
        """Run fuzzing_validation.py for a specific file"""
        try:
            print(f"Running validation for: {os.path.basename(filepath)}")
            self.validation_process = subprocess.Popen(
                [sys.executable, "fuzzing_validation.py", filepath],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Wait for validation to complete
            stdout, stderr = self.validation_process.communicate()
            
            if self.validation_process.returncode == 0:
                print(f"✓ Validation completed successfully for {os.path.basename(filepath)}")
                return True
            else:
                print(f"✗ Validation failed for {os.path.basename(filepath)} (return code: {self.validation_process.returncode})")
                if stderr:
                    print(f"Error: {stderr.decode()}")
                return False
                
        except Exception as e:
            print(f"Error running validation for {os.path.basename(filepath)}: {e}")
            return False
    
    def cleanup_processes(self):
        """Clean up all running processes"""
        if self.cleanup_done:
            return
        
        try:
            # Clean up validation process
            if self.validation_process and self.validation_process.poll() is None:
                print("Terminating validation process...")
                self.validation_process.terminate()
                self.validation_process.wait(timeout=5)
            
            # Clean up simulator terminal using terminal manager
            print("Closing simulator terminal...")
            self.terminal_manager.close_terminal()
            
            self.cleanup_done = True
                
        except Exception as e:
            print(f"Error during cleanup: {e}")
            self.cleanup_done = True
    
    def signal_handler(self, signum, frame):
        """Handle interrupt signals gracefully"""
        print("\nReceived interrupt signal. Cleaning up...")
        self.cleanup_processes()
        print("Cleanup completed. Exiting...")
        sys.exit(0)
    
    def run_automation(self):
        """Main automation loop"""
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Get all files to process
        start_file = None
        if len(sys.argv) > 2:
            start_file = sys.argv[2]
        
        files = self.get_all_files(start_file)
        self.total_files = len(files)
        
        if self.total_files == 0:
            print("No files found in policy_violations directory")
            return
        
        print(f"Found {self.total_files} files to process")
        print("=" * 50)
        
        try:
            for i, filepath in enumerate(files, 1):
                print(f"\n[{i}/{self.total_files}] Processing: {os.path.basename(filepath)}")
                
                # Check if file is empty
                if self.is_file_empty(filepath):
                    print(f"⚠ Skipping empty file: {os.path.basename(filepath)}")
                    self.skipped_files += 1
                    continue
                
                # Start simulator
                if not self.start_simulator():
                    print("Failed to start simulator. Aborting.")
                    break
                
                # Run validation
                success = self.run_validation(filepath)
                self.processed_files += 1
                
                # Cleanup before next iteration
                self.cleanup_processes()
                
                # Reset terminal manager for next iteration
                self.terminal_manager.reset()
                self.cleanup_done = False
                
                # Brief pause between iterations
                time.sleep(2)
                
        except KeyboardInterrupt:
            print("\nAutomation interrupted by user")
        except Exception as e:
            print(f"Unexpected error: {e}")
        finally:
            # Final cleanup
            self.cleanup_processes()
            
        # Print summary
        print("\n" + "=" * 50)
        print("AUTOMATION SUMMARY")
        print("=" * 50)
        print(f"Total files: {self.total_files}")
        print(f"Processed: {self.processed_files}")
        print(f"Skipped (empty): {self.skipped_files}")
        print(f"Remaining: {self.total_files - self.processed_files - self.skipped_files}")

def main():
    """Main entry point"""
    if len(sys.argv) > 1:
        policy_violations_dir = sys.argv[1]
    else:
        policy_violations_dir = "policy_violations"
    
    if not os.path.exists(policy_violations_dir):
        print(f"Error: Directory '{policy_violations_dir}' does not exist")
        sys.exit(1)
    
    automator = ValidationAutomator(policy_violations_dir)
    automator.run_automation()

if __name__ == "__main__":
    main()
