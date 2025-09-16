#!/usr/bin/env python3
"""
Enhanced Crash Verification Script with MAVLink Message Monitoring
Author: AI Assistant
Date: 2024
Purpose: Verify if policy violation commands cause drone crashes while monitoring all MAVLink messages
"""

import os
import sys
import time
import threading
import subprocess
import signal
import psutil
import json
import glob
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any
from multiprocessing import Process, Queue, Event
from collections import defaultdict, Counter

# Add mavlink path
sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), '../mavlink'))
from pymavlink import mavutil, mavwp
from pymavlink import mavextra
from pymavlink import mavexpression

class MAVLinkMonitor:
    """MAVLink message monitoring class"""
    
    def __init__(self, connection_string: str = 'udp:127.0.0.1:14550'):
        self.connection_string = connection_string
        self.master = None
        self.monitoring = False
        self.messages = []
        self.message_stats = Counter()
        self.start_time = None
        self.monitor_thread = None
        self.stop_event = threading.Event()
        
    def start_monitoring(self):
        """Start monitoring MAVLink messages in a separate thread"""
        if self.monitoring:
            return False
            
        try:
            # Connect to MAVProxy
            self.master = mavutil.mavlink_connection(self.connection_string)
            self.master.wait_heartbeat()
            
            # Start monitoring thread
            self.monitoring = True
            self.start_time = time.time()
            self.stop_event.clear()
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()
            
            print(f"[MONITOR] Started MAVLink message monitoring")
            return True
            
        except Exception as e:
            print(f"[MONITOR] Failed to start monitoring: {e}")
            return False
    
    def stop_monitoring(self):
        """Stop monitoring and return collected messages"""
        if not self.monitoring:
            return []
            
        self.monitoring = False
        self.stop_event.set()
        
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2)
        
        if self.master:
            try:
                self.master.close()
            except:
                pass
            self.master = None
        
        print(f"[MONITOR] Stopped monitoring. Collected {len(self.messages)} messages")
        return self.messages.copy()
    
    def _monitor_loop(self):
        """Main monitoring loop"""
        try:
            while self.monitoring and not self.stop_event.is_set():
                # Receive message with timeout
                msg = self.master.recv_match(blocking=True, timeout=0.1)
                
                if msg is not None:
                    # Format message
                    message_data = self._format_message(msg)
                    
                    # Store message
                    self.messages.append(message_data)
                    self.message_stats[message_data['type']] += 1
                    
        except Exception as e:
            print(f"[MONITOR] Error in monitoring loop: {e}")
        finally:
            self.monitoring = False
    
    def _format_message(self, msg) -> Dict[str, Any]:
        """Format a MAVLink message for storage"""
        try:
            msg_type = msg.get_type()
            timestamp = datetime.now().isoformat()
            
            message_data = {
                'timestamp': timestamp,
                'type': msg_type,
                'system_id': getattr(msg, 'get_srcSystem', lambda: None)(),
                'component_id': getattr(msg, 'get_srcComponent', lambda: None)(),
                'sequence': getattr(msg, 'get_seq', lambda: None)(),
                'data': {}
            }
            
            # Extract all fields from the message
            if hasattr(msg, '__dict__'):
                for field_name, field_value in msg.__dict__.items():
                    if not field_name.startswith('_'):
                        # Convert numpy types to Python types for JSON serialization
                        try:
                            if hasattr(field_value, 'item'):  # numpy scalar
                                field_value = field_value.item()
                            elif hasattr(field_value, 'tolist'):  # numpy array
                                field_value = field_value.tolist()
                        except (AttributeError, ValueError):
                            pass
                        
                        message_data['data'][field_name] = field_value
            
            return message_data
            
        except Exception as e:
            return {
                'timestamp': datetime.now().isoformat(),
                'type': 'ERROR',
                'error': str(e),
                'raw_message': str(msg)
            }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get monitoring statistics"""
        runtime = time.time() - self.start_time if self.start_time else 0
        return {
            'total_messages': len(self.messages),
            'message_types': len(self.message_stats),
            'runtime': runtime,
            'message_counts': dict(self.message_stats),
            'start_time': self.start_time
        }

class EnhancedCrashVerifier:
    def __init__(self, violations_dir: str = "policy_violations910", 
                 ardupilot_home: str = "/home/bonnie/PGFuzz/ardupilot_pgfuzz/",
                 output_dir: str = "verification_results"):
        """
        Initialize the enhanced crash verifier with MAVLink monitoring
        
        Args:
            violations_dir: Directory containing policy violation files
            ardupilot_home: Path to ArduPilot installation
            output_dir: Directory to save results and MAVLink logs
        """
        self.violations_dir = violations_dir
        self.ardupilot_home = ardupilot_home
        self.output_dir = output_dir
        self.results = []
        self.sim_process = None
        self.master = None
        self.mavlink_monitor = None
        
        # Create output directory
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Crash detection variables
        self.crash_indicators = {
            'hit_ground': False,
            'system_crash': False,
            'communication_lost': False,
            'failsafe_triggered': False,
            'parachute_deployed': False,
            'altitude_drop': False,
            'uncontrolled_flight': False
        }
        
        # Flight state monitoring
        self.flight_state = {
            'altitude': 0.0,
            'previous_altitude': 0.0,
            'ground_speed': 0.0,
            'armed': False,
            'flight_mode': '',
            'system_status': 0,
            'heartbeat_count': 0,
            'last_heartbeat': time.time()
        }
        
        # Test configuration
        self.test_config = {
            'max_test_duration': 10,  # seconds
            'altitude_threshold': 5.0,  # meters - significant altitude drop
            'ground_impact_threshold': 1.0,  # meters - close to ground
            'heartbeat_timeout': 8.0,  # seconds
            'max_altitude_drop_rate': -10.0,  # m/s - rapid descent
            'command_wait_time': 0.0  # seconds to wait after commands
        }

        # Resolve violations directory when running from analysis_910
        try:
            if not os.path.isabs(self.violations_dir) and not os.path.isdir(self.violations_dir):
                base_dir = os.path.dirname(os.path.realpath(__file__))
                alt_path = os.path.abspath(os.path.join(base_dir, '..', self.violations_dir))
                if os.path.isdir(alt_path):
                    self.violations_dir = alt_path
        except Exception:
            pass
        
    def start_simulator(self) -> bool:
        """Start the ArduPilot simulator"""
        try:
            # Command to start simulator
            cmd = "gnome-terminal -- " + self.ardupilot_home + 'Tools/autotest/sim_vehicle.py -v ArduCopter -S 40 --console --map --debug -w'
            print("[VERIFIER] Starting ArduPilot simulator...", cmd)
            
            # Start simulator process
            self.sim_process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True
            )
            
            # Wait for simulator to start
            time.sleep(25)
            
            # Connect to simulator
            self.master = mavutil.mavlink_connection('udp:127.0.0.1:14550')
            self.master.wait_heartbeat()
            
            print("[VERIFIER] Simulator started and connected successfully")
            return True
            
        except Exception as e:
            print(f"[VERIFIER] Failed to start simulator: {e}")
            return False
    
    def stop_simulator(self):
        """Stop the ArduPilot simulator"""
        try:
            if self.sim_process:
                print("[VERIFIER] Stopping simulator...")
                os.killpg(os.getpgid(self.sim_process.pid), signal.SIGTERM)
                self.sim_process.wait(timeout=10)
                self.sim_process = None
                
            if self.master:
                self.master.close()
                self.master = None
                
            print("[VERIFIER] Simulator stopped")
            
        except Exception as e:
            print(f"[VERIFIER] Error stopping simulator: {e}")
    
    def setup_drone(self) -> bool:
        """Setup drone for testing (takeoff, arm, etc.)"""
        try:
            print("[VERIFIER] Setting up drone for testing...")
            
            # Request data streams at higher rate (20 Hz instead of 6 Hz)
            for i in range(3):
                self.master.mav.request_data_stream_send(
                    self.master.target_system, 
                    self.master.target_component,
                    mavutil.mavlink.MAV_DATA_STREAM_ALL, 20, 1
                )
            
            # Request specific high-frequency streams
            self.master.mav.request_data_stream_send(
                self.master.target_system, 
                self.master.target_component,
                mavutil.mavlink.MAV_DATA_STREAM_EXTRA1, 20, 1  # Attitude, IMU, etc.
            )
            self.master.mav.request_data_stream_send(
                self.master.target_system, 
                self.master.target_component,
                mavutil.mavlink.MAV_DATA_STREAM_EXTRA2, 20, 1  # VFR_HUD, GPS, etc.
            )
            self.master.mav.request_data_stream_send(
                self.master.target_system, 
                self.master.target_component,
                mavutil.mavlink.MAV_DATA_STREAM_EXTRA3, 20, 1  # RC channels, etc.
            )
            
            # Get home position
            message = self.master.recv_match(type='VFR_HUD', blocking=True, timeout=5)
            if message:
                self.flight_state['altitude'] = message.alt
                print(f"[VERIFIER] Home altitude: {self.flight_state['altitude']}")
            
            # Set to GUIDED mode
            mode_id = self.master.mode_mapping()['GUIDED']
            print(f"[DEBUG] Sending mode change to GUIDED (mode_id: {mode_id})")
            self.master.mav.set_mode_send(
                self.master.target_system,
                mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                mode_id
            )
            
            # Wait for mode change
            time.sleep(0.02)
            
            # Arm the drone
            print(f"[DEBUG] Sending ARM command (MAV_CMD_COMPONENT_ARM_DISARM)")
            self.master.mav.command_long_send(
                self.master.target_system,
                self.master.target_component,
                mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                0, 1, 0, 0, 0, 0, 0, 0
            )
            
            # Wait for arming
            time.sleep(0.02)
            
            # Takeoff
            print(f"[DEBUG] Sending TAKEOFF command (MAV_CMD_NAV_TAKEOFF) to 100m altitude")
            self.master.mav.command_long_send(
                self.master.target_system,
                self.master.target_component,
                mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                0, 0, 0, 0, 0, 0, 0, 100  # 100m altitude
            )

            # Wait for takeoff by polling altitude or timeout (~20s)
            start_wait = time.time()
            reached_alt = False
            while time.time() - start_wait < 4:
                hud = self.master.recv_match(type='GLOBAL_POSITION_INT', blocking=True, timeout=2)
                if hud is not None and getattr(hud, 'relative_alt', 0) >= 95:
                    reached_alt = True
                    break
            if not reached_alt:
                print("[VERIFIER] Warning: target altitude not reached within timeout")
            
            print("[VERIFIER] Drone setup completed")
            return True
            
        except Exception as e:
            print(f"[VERIFIER] Failed to setup drone: {e}")
            return False
    
    def parse_violation_file(self, filepath: str) -> List[Dict]:
        """Parse a violation file and return list of commands"""
        commands = []
        
        try:
            with open(filepath, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    
                    parts = line.split(' ', 2)
                    if len(parts) < 2:
                        continue
                    
                    cmd_type = parts[0]
                    cmd_name = parts[1]
                    cmd_value = parts[2] if len(parts) > 2 else ""
                    
                    commands.append({
                        'line': line_num,
                        'type': cmd_type,
                        'name': cmd_name,
                        'value': cmd_value,
                        'original': line
                    })
                    
        except Exception as e:
            print(f"[VERIFIER] Error parsing {filepath}: {e}")
            
        return commands
    
    def execute_command(self, cmd: Dict) -> bool:
        """Execute a single command"""
        try:
            cmd_type = cmd['type']
            cmd_name = cmd['name']
            cmd_value = cmd['value']
            
            print(f"[DEBUG] Executing command: {cmd_type} {cmd_name} {cmd_value}")
            
            if cmd_type == 'P':  # Parameter
                return self._execute_parameter(cmd_name, cmd_value)
            elif cmd_type == 'C':  # Command
                return self._execute_mavlink_command(cmd_name, cmd_value)
            elif cmd_type == 'E':  # Environmental
                return self._execute_environmental(cmd_name, cmd_value)
            else:
                print(f"[VERIFIER] Unknown command type: {cmd_type}")
                return False
                
        except Exception as e:
            print(f"[VERIFIER] Error executing command {cmd}: {e}")
            return False
    
    def _execute_parameter(self, param_name: str, param_value: str) -> bool:
        """Execute parameter change"""
        try:
            value = float(param_value)
            print(f"[DEBUG] Setting parameter: {param_name} = {value}")
            self.master.mav.param_set_send(
                self.master.target_system,
                self.master.target_component,
                param_name.encode("ascii")[:16],
                value,
                mavutil.mavlink.MAV_PARAM_TYPE_REAL32
            )
            time.sleep(0.02)
            return True
        except Exception as e:
            print(f"[VERIFIER] Error setting parameter {param_name}: {e}")
            return False
    
    def _execute_mavlink_command(self, cmd_name: str, cmd_value: str) -> bool:
        """Execute MAVLink command"""
        try:
            if cmd_name.startswith('RC'):
                # RC channel command
                channel = int(cmd_name[2:])
                value = int(cmd_value)
                print(f"[DEBUG] Setting RC channel {channel} to {value}")
                self._set_rc_channel(channel, value)
                time.sleep(0.02)
                return True
            elif cmd_name == 'Flight_Mode':
                # Flight mode change
                mode_id = int(cmd_value)
                print(f"[DEBUG] Changing flight mode to {mode_id}")
                self.master.mav.set_mode_send(
                    self.master.target_system,
                    mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                    mode_id
                )
                time.sleep(0.02)
                return True
            elif cmd_name.startswith('MAV_CMD_'):
                # MAVLink command
                cmd_id = getattr(mavutil.mavlink, cmd_name, None)
                if cmd_id is None:
                    print(f"[VERIFIER] Unknown MAVLink command: {cmd_name}")
                    return False
                
                # Parse parameters
                params = [0] * 7
                if cmd_value:
                    param_values = cmd_value.split(',')
                    for i, val in enumerate(param_values[:7]):
                        try:
                            params[i] = int(val)
                        except ValueError:
                            try:
                                params[i] = float(val)
                            except ValueError:
                                params[i] = 0
                
                print(f"[DEBUG] Sending MAVLink command: {cmd_name} (ID: {cmd_id}) with params: {params}")
                self.master.mav.command_long_send(
                    self.master.target_system,
                    self.master.target_component,
                    cmd_id,
                    0, *params
                )
                time.sleep(0.02)
                return True
            else:
                print(f"[VERIFIER] Unknown command: {cmd_name}")
                return False
                
        except Exception as e:
            print(f"[VERIFIER] Error executing MAVLink command {cmd_name}: {e}")
            return False
    
    def _execute_environmental(self, env_name: str, env_value: str) -> bool:
        """Execute environmental factor change"""
        try:
            value = float(env_value)
            print(f"[DEBUG] Setting environmental parameter: {env_name} = {value}")
            self.master.mav.param_set_send(
                self.master.target_system,
                self.master.target_component,
                env_name.encode("ascii")[:16],
                value,
                mavutil.mavlink.MAV_PARAM_TYPE_REAL32
            )
            time.sleep(0.02)
            return True
        except Exception as e:
            print(f"[VERIFIER] Error setting environmental factor {env_name}: {e}")
            return False
    
    def _set_rc_channel(self, channel: int, pwm: int):
        """Set RC channel PWM value"""
        rc_channel_values = [65535 for _ in range(8)]
        rc_channel_values[channel - 1] = pwm
        
        print(f"[DEBUG] Sending RC channels override: channel {channel} = {pwm}")
        self.master.mav.rc_channels_override_send(
            self.master.target_system,
            self.master.target_component,
            *rc_channel_values
        )
    
    def test_violation_sequence_with_monitoring(self, violation_file: str) -> Dict:
        """Test a single violation sequence with MAVLink monitoring"""
        print(f"\n[VERIFIER] Testing violation file: {violation_file}")
        
        # Reset crash indicators
        for key in self.crash_indicators:
            self.crash_indicators[key] = False
        
        # Parse violation commands
        commands = self.parse_violation_file(violation_file)
        if not commands:
            return {
                'file': violation_file,
                'crashed': False,
                'reason': 'No valid commands found',
                'commands_executed': 0,
                'crash_indicators': self.crash_indicators.copy(),
                'mavlink_messages': [],
                'mavlink_stats': {}
            }
        
        # Mark the start of this test in the continuous log
        if self.mavlink_monitor:
            test_start_time = time.time()
            # Add a marker message to indicate test start
            test_marker = {
                'timestamp': datetime.now().isoformat(),
                'type': 'TEST_MARKER',
                'system_id': 255,
                'component_id': 255,
                'sequence': 0,
                'data': {
                    'test_file': os.path.basename(violation_file),
                    'test_start_time': test_start_time,
                    'message': f"Starting test: {os.path.basename(violation_file)}"
                }
            }
            self.mavlink_monitor.messages.append(test_marker)
        else:
            print("[VERIFIER] Warning: MAVLink monitor not available")
        
        # Execute commands
        commands_executed = 0
        start_time = time.time()
        
        try:
            for i, cmd in enumerate(commands):
                print(f"[VERIFIER] Executing command {i+1}/{len(commands)}: {cmd['original']}")
                
                if self.execute_command(cmd):
                    commands_executed += 1
                    # time.sleep(0.5)  # Wait between commands
                else:
                    print(f"[VERIFIER] Failed to execute command: {cmd['original']}")
            
            # Wait for commands to finish executing
            # print(f"[VERIFIER] Waiting {self.test_config['command_wait_time']} seconds for commands to finish...")
            # time.sleep(self.test_config['command_wait_time'])
            
        except Exception as e:
            print(f"[VERIFIER] Error during command execution: {e}")
            self.crash_indicators['system_crash'] = True
        
        # Collect messages from the ongoing monitor for this specific test
        if self.mavlink_monitor:
            # Add end marker for this test
            test_end_marker = {
                'timestamp': datetime.now().isoformat(),
                'type': 'TEST_MARKER',
                'system_id': 255,
                'component_id': 255,
                'sequence': 0,
                'data': {
                    'test_file': os.path.basename(violation_file),
                    'test_end_time': time.time(),
                    'message': f"Ending test: {os.path.basename(violation_file)}"
                }
            }
            self.mavlink_monitor.messages.append(test_end_marker)
            
            # Get all messages (complete session log)
            mavlink_messages = self.mavlink_monitor.messages.copy()
            mavlink_stats = self.mavlink_monitor.get_stats()
        else:
            mavlink_messages = []
            mavlink_stats = {}
        
        # Filter messages for this specific test and analyze
        test_specific_messages = self._filter_messages_by_test(mavlink_messages, violation_file)
        self._analyze_mavlink_messages(test_specific_messages)
        
        # Determine if crash occurred
        crashed = any(self.crash_indicators.values())
        crash_reason = "No crash detected"
        
        if crashed:
            priority = ['hit_ground','parachute_deployed','failsafe_triggered','altitude_drop','system_crash','communication_lost']
            active_indicators = [k for k in priority if self.crash_indicators.get(k)]
            if not active_indicators:
                active_indicators = [k for k, v in self.crash_indicators.items() if v]
            crash_reason = f"Crash indicators: {', '.join(active_indicators)}"
        
        # Save MAVLink messages to file (both complete session and test-specific)
        filename_base = os.path.splitext(os.path.basename(violation_file))[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save complete session log
        session_filename = os.path.join(self.output_dir, f"session_complete_{timestamp}.json")
        self._save_mavlink_messages(mavlink_messages, mavlink_stats, session_filename)
        
        # Save test-specific messages
        test_filename = os.path.join(self.output_dir, f"test_{filename_base}_{timestamp}.json")
        self._save_mavlink_messages(test_specific_messages, mavlink_stats, test_filename)
        
        mavlink_filename = test_filename  # Use test-specific filename for result
        
        result = {
            'file': violation_file,
            'crashed': crashed,
            'reason': crash_reason,
            'commands_executed': commands_executed,
            'total_commands': len(commands),
            'test_duration': time.time() - start_time,
            'crash_indicators': self.crash_indicators.copy(),
            'mavlink_messages': mavlink_messages,
            'mavlink_stats': mavlink_stats,
            'mavlink_log_file': mavlink_filename
        }
        
        print(f"[VERIFIER] Test completed - Crashed: {crashed}, Reason: {crash_reason}")
        print(f"[VERIFIER] MAVLink messages saved to: {mavlink_filename}")
        return result
    
    def _filter_messages_by_test(self, messages: List[Dict], test_file: str) -> List[Dict]:
        """Filter messages to only include those from a specific test"""
        test_messages = []
        in_test = False
        test_start_time = None
        
        for msg in messages:
            if msg.get('type') == 'TEST_MARKER':
                marker_data = msg.get('data', {})
                if marker_data.get('test_file') == os.path.basename(test_file):
                    if 'test_start_time' in marker_data:
                        in_test = True
                        test_start_time = marker_data['test_start_time']
                        test_messages.append(msg)  # Include the start marker
                    elif 'test_end_time' in marker_data:
                        in_test = False
                        test_messages.append(msg)  # Include the end marker
                        break
            elif in_test:
                test_messages.append(msg)
        
        return test_messages
    
    def _analyze_mavlink_messages(self, messages: List[Dict]):
        """Analyze MAVLink messages for crash indicators"""
        for msg in messages:
            msg_type = msg.get('type', '')
            data = msg.get('data', {})
            
            if msg_type == 'STATUSTEXT':
                text = data.get('text', '').lower()
                if 'hit ground' in text:
                    self.crash_indicators['hit_ground'] = True
                elif 'parachute' in text and 'released' in text:
                    self.crash_indicators['parachute_deployed'] = True
                elif 'failsafe' in text and 'cleared' not in text:
                    self.crash_indicators['failsafe_triggered'] = True
            
            elif msg_type == 'VFR_HUD':
                alt = data.get('alt', 0)
                if alt < self.test_config['ground_impact_threshold']:
                    self.crash_indicators['hit_ground'] = True
            
            elif msg_type == 'HEARTBEAT':
                system_status = data.get('system_status', 0)
                if system_status == 4:  # MAV_STATE_CRITICAL
                    self.crash_indicators['system_crash'] = True
    
    def _save_mavlink_messages(self, messages: List[Dict], stats: Dict, filename: str):
        """Save MAVLink messages to JSON file"""
        try:
            output_data = {
                'metadata': {
                    'timestamp': datetime.now().isoformat(),
                    'total_messages': len(messages),
                    'message_types': stats.get('message_types', 0),
                    'runtime': stats.get('runtime', 0),
                    'connection_string': 'udp:127.0.0.1:14550'
                },
                'statistics': {
                    'message_counts': stats.get('message_counts', {}),
                    'message_types': list(stats.get('message_counts', {}).keys())
                },
                'messages': messages
            }
            
            with open(filename, 'w') as f:
                json.dump(output_data, f, indent=2)
                
        except Exception as e:
            print(f"[VERIFIER] Error saving MAVLink messages: {e}")
    
    def verify_all_violations(self, max_files: Optional[int] = None) -> List[Dict]:
        """Verify all violation files with MAVLink monitoring"""
        print(f"[VERIFIER] Starting verification of violations in {self.violations_dir}")
        
        # Get all violation files
        violation_files = glob.glob(os.path.join(self.violations_dir, "*.txt"))
        violation_files.sort()
        
        if max_files:
            violation_files = violation_files[:max_files]
        
        print(f"[VERIFIER] Found {len(violation_files)} violation files to test")
        
        # Start simulator
        if not self.start_simulator():
            print("[VERIFIER] Failed to start simulator")
            return []
        
        try:
            # Start MAVLink monitoring after simulator is running
            print("[VERIFIER] Starting MAVLink monitoring...")
            self.mavlink_monitor = MAVLinkMonitor()
            if not self.mavlink_monitor.start_monitoring():
                print("[VERIFIER] Warning: Failed to start MAVLink monitoring")
            
            # Setup drone
            if not self.setup_drone():
                print("[VERIFIER] Failed to setup drone")
                return []
            
            # Test each violation file
            for i, violation_file in enumerate(violation_files):
                print(f"\n[VERIFIER] Progress: {i+1}/{len(violation_files)}")

                # Skip empty files (no commands)
                try:
                    with open(violation_file, 'r') as f:
                        has_content = any(line.strip() for line in f)
                except Exception:
                    has_content = False

                if not has_content:
                    print(f"[VERIFIER] Skipping empty file: {os.path.basename(violation_file)}")
                    continue

                result = self.test_violation_sequence_with_monitoring(violation_file)
                self.results.append(result)
                
                # Reset drone state for next test
                # self._reset_drone_state()
                
                # Save intermediate results
                if (i + 1) % 10 == 0:
                    self.save_results(f"verification_results_partial_{i+1}.json")
            
        finally:
            # Stop MAVLink monitoring
            if self.mavlink_monitor:
                print("[VERIFIER] Stopping MAVLink monitoring...")
                self.mavlink_monitor.stop_monitoring()
            self.stop_simulator()
        
        return self.results
    
    def _reset_drone_state(self):
        """Reset drone to a safe state for next test"""
        try:
            # Set to GUIDED mode
            mode_id = self.master.mode_mapping()['GUIDED']
            self.master.mav.set_mode_send(
                self.master.target_system,
                mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                mode_id
            )
            
            # Reset RC channels to neutral
            for channel in range(1, 9):
                self._set_rc_channel(channel, 1500)
            
            time.sleep(2)
            
        except Exception as e:
            print(f"[VERIFIER] Error resetting drone state: {e}")
    
    def save_results(self, filename: str = None):
        """Save verification results to JSON file"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"crash_verification_results_{timestamp}.json"
        
        # Don't include full MAVLink messages in results file (too large)
        results_for_save = []
        for result in self.results:
            result_copy = result.copy()
            result_copy['mavlink_messages'] = []  # Remove messages to keep file size manageable
            results_for_save.append(result_copy)
        
        try:
            with open(filename, 'w') as f:
                json.dump({
                    'timestamp': datetime.now().isoformat(),
                    'total_tests': len(self.results),
                    'crashes_detected': sum(1 for r in self.results if r['crashed']),
                    'results': results_for_save
                }, f, indent=2)
            
            print(f"[VERIFIER] Results saved to {filename}")
            
        except Exception as e:
            print(f"[VERIFIER] Error saving results: {e}")
    
    def print_summary(self):
        """Print verification summary"""
        if not self.results:
            print("[VERIFIER] No results to summarize")
            return
        
        total_tests = len(self.results)
        crashes = sum(1 for r in self.results if r['crashed'])
        crash_rate = (crashes / total_tests) * 100 if total_tests > 0 else 0
        
        print(f"\n[VERIFIER] VERIFICATION SUMMARY")
        print(f"[VERIFIER] Total tests: {total_tests}")
        print(f"[VERIFIER] Crashes detected: {crashes}")
        print(f"[VERIFIER] Crash rate: {crash_rate:.1f}%")
        
        # Show crash breakdown by indicator
        indicator_counts = {}
        for result in self.results:
            if result['crashed']:
                for indicator, active in result['crash_indicators'].items():
                    if active:
                        indicator_counts[indicator] = indicator_counts.get(indicator, 0) + 1
        
        if indicator_counts:
            print(f"\n[VERIFIER] Crash indicators breakdown:")
            for indicator, count in sorted(indicator_counts.items()):
                print(f"[VERIFIER]   {indicator}: {count}")
        
        # Show MAVLink monitoring summary
        total_messages = sum(r['mavlink_stats'].get('total_messages', 0) for r in self.results)
        print(f"\n[VERIFIER] MAVLink monitoring summary:")
        print(f"[VERIFIER] Total messages collected: {total_messages}")
        print(f"[VERIFIER] MAVLink logs saved in: {self.output_dir}")

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Verify if policy violations cause drone crashes with MAVLink monitoring')
    parser.add_argument('--violations-dir', default='policy_violations910',
                       help='Directory containing violation files')
    parser.add_argument('--ardupilot-home', default='/home/bonnie/PGFuzz/ardupilot_pgfuzz/',
                       help='ArduPilot installation directory')
    parser.add_argument('--max-files', type=int, default=None,
                       help='Maximum number of files to test')
    parser.add_argument('--output', default=None,
                       help='Output filename for results')
    parser.add_argument('--output-dir', default='verification_results',
                       help='Directory for MAVLink message logs')
    
    args = parser.parse_args()
    
    # Create verifier
    verifier = EnhancedCrashVerifier(
        violations_dir=args.violations_dir,
        ardupilot_home=args.ardupilot_home,
        output_dir=args.output_dir
    )
    
    try:
        # Run verification
        results = verifier.verify_all_violations(max_files=args.max_files)
        
        # Save and print results
        verifier.save_results(args.output)
        verifier.print_summary()
        
    except KeyboardInterrupt:
        print("\n[VERIFIER] Verification interrupted by user")
        verifier.stop_simulator()
    except Exception as e:
        print(f"[VERIFIER] Verification failed: {e}")
        verifier.stop_simulator()

if __name__ == "__main__":
    main()
