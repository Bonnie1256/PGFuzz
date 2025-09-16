#!/usr/bin/env python3
"""
Comprehensive MAVLink Message Receiver
Author: AI Assistant
Date: 2024
Purpose: Receive and log ALL MAVLink messages from MAVProxy
"""

import os
import sys
import time
import json
import signal
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any
from collections import defaultdict, Counter

# Add mavlink path
sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), '../mavlink'))
from pymavlink import mavutil

class MAVLinkMessageReceiver:
    def __init__(self, connection_string: str = 'udp:127.0.0.1:14550', 
                 output_file: Optional[str] = None, 
                 verbose: bool = True):
        """
        Initialize the MAVLink message receiver
        
        Args:
            connection_string: MAVLink connection string (default: udp:127.0.0.1:14550)
            output_file: Optional file to save all messages to JSON
            verbose: Whether to print messages to console
        """
        self.connection_string = connection_string
        self.output_file = output_file
        self.verbose = verbose
        self.master = None
        self.running = False
        self.message_count = 0
        self.start_time = None
        
        # Message statistics
        self.message_stats = Counter()
        self.message_timestamps = defaultdict(list)
        self.unique_messages = set()
        
        # Message storage
        self.all_messages = []
        self.messages_by_type = defaultdict(list)
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        print(f"\n[RECEIVER] Received signal {signum}, shutting down gracefully...")
        self.stop()
        
    def connect(self) -> bool:
        """Connect to MAVProxy"""
        try:
            print(f"[RECEIVER] Connecting to {self.connection_string}...")
            self.master = mavutil.mavlink_connection(self.connection_string)
            
            # Wait for heartbeat to confirm connection
            print("[RECEIVER] Waiting for heartbeat...")
            self.master.wait_heartbeat()
            print(f"[RECEIVER] Connected! System ID: {self.master.target_system}, Component ID: {self.master.target_component}")
            
            return True
            
        except Exception as e:
            print(f"[RECEIVER] Failed to connect: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from MAVProxy"""
        if self.master:
            try:
                self.master.close()
                print("[RECEIVER] Disconnected from MAVProxy")
            except Exception as e:
                print(f"[RECEIVER] Error during disconnect: {e}")
            finally:
                self.master = None
    
    def _format_message(self, msg) -> Dict[str, Any]:
        """Format a MAVLink message for logging"""
        try:
            # Get basic message info
            msg_type = msg.get_type()
            timestamp = datetime.now().isoformat()
            
            # Create message dictionary
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
            print(f"[RECEIVER] Error formatting message: {e}")
            return {
                'timestamp': datetime.now().isoformat(),
                'type': 'ERROR',
                'error': str(e),
                'raw_message': str(msg)
            }
    
    def _print_message(self, message_data: Dict[str, Any]):
        """Print message to console if verbose mode is enabled"""
        if not self.verbose:
            return
            
        msg_type = message_data['type']
        timestamp = message_data['timestamp']
        data = message_data.get('data', {})
        
        # Print basic message info
        print(f"[{timestamp}] {msg_type}")
        
        # Print key fields for common message types
        if msg_type == 'HEARTBEAT':
            print(f"  System Status: {data.get('system_status', 'N/A')}")
            print(f"  Base Mode: {data.get('base_mode', 'N/A')}")
            print(f"  Custom Mode: {data.get('custom_mode', 'N/A')}")
        elif msg_type == 'VFR_HUD':
            print(f"  Altitude: {data.get('alt', 'N/A')} m")
            print(f"  Ground Speed: {data.get('groundspeed', 'N/A')} m/s")
            print(f"  Heading: {data.get('heading', 'N/A')}°")
        elif msg_type == 'ATTITUDE':
            print(f"  Roll: {data.get('roll', 'N/A')} rad")
            print(f"  Pitch: {data.get('pitch', 'N/A')} rad")
            print(f"  Yaw: {data.get('yaw', 'N/A')} rad")
        elif msg_type == 'GLOBAL_POSITION_INT':
            print(f"  Lat: {data.get('lat', 'N/A')} / 1e7")
            print(f"  Lon: {data.get('lon', 'N/A')} / 1e7")
            print(f"  Alt: {data.get('alt', 'N/A')} mm")
        elif msg_type == 'STATUSTEXT':
            print(f"  Text: {data.get('text', 'N/A')}")
        elif msg_type == 'RC_CHANNELS':
            print(f"  Channels: {[data.get(f'chan{i}_raw', 'N/A') for i in range(1, 9)]}")
        elif msg_type == 'PARAM_VALUE':
            print(f"  Param: {data.get('param_id', 'N/A')} = {data.get('param_value', 'N/A')}")
        else:
            # For unknown message types, print first few fields
            field_count = 0
            for field_name, field_value in data.items():
                if field_count < 5:  # Limit to first 5 fields
                    print(f"  {field_name}: {field_value}")
                    field_count += 1
                else:
                    remaining = len(data) - 5
                    if remaining > 0:
                        print(f"  ... and {remaining} more fields")
                    break
        
        print()  # Empty line for readability
    
    def _save_message(self, message_data: Dict[str, Any]):
        """Save message to storage"""
        # Add to all messages
        self.all_messages.append(message_data)
        
        # Add to type-specific storage
        msg_type = message_data['type']
        self.messages_by_type[msg_type].append(message_data)
        
        # Update statistics
        self.message_stats[msg_type] += 1
        self.message_timestamps[msg_type].append(message_data['timestamp'])
        
        # Create unique identifier for deduplication
        unique_id = f"{msg_type}_{message_data.get('system_id', '')}_{message_data.get('component_id', '')}_{message_data.get('sequence', '')}"
        self.unique_messages.add(unique_id)
    
    def _periodic_stats(self):
        """Print periodic statistics"""
        while self.running:
            time.sleep(30)  # Print stats every 30 seconds
            if self.running and self.message_count > 0:
                runtime = time.time() - self.start_time
                rate = self.message_count / runtime if runtime > 0 else 0
                
                print(f"\n[RECEIVER] STATS - Runtime: {runtime:.1f}s, Messages: {self.message_count}, Rate: {rate:.1f} msg/s")
                print(f"[RECEIVER] Top message types:")
                for msg_type, count in self.message_stats.most_common(5):
                    print(f"  {msg_type}: {count}")
                print()
    
    def start_receiving(self):
        """Start receiving messages"""
        if not self.master:
            print("[RECEIVER] Not connected to MAVProxy")
            return False
        
        print("[RECEIVER] Starting message reception...")
        print("[RECEIVER] Press Ctrl+C to stop")
        print()
        
        self.running = True
        self.start_time = time.time()
        
        # Start statistics thread
        stats_thread = threading.Thread(target=self._periodic_stats, daemon=True)
        stats_thread.start()
        
        try:
            while self.running:
                # Receive message with timeout
                msg = self.master.recv_match(blocking=True, timeout=1.0)
                
                if msg is not None:
                    # Format and process message
                    message_data = self._format_message(msg)
                    
                    # Print to console
                    self._print_message(message_data)
                    
                    # Save to storage
                    self._save_message(message_data)
                    
                    # Increment counter
                    self.message_count += 1
                    
                # Check for timeout (no message received)
                if msg is None and self.running:
                    # Optional: print timeout message
                    pass
                    
        except KeyboardInterrupt:
            print("\n[RECEIVER] Interrupted by user")
        except Exception as e:
            print(f"[RECEIVER] Error during message reception: {e}")
        finally:
            self.running = False
    
    def stop(self):
        """Stop receiving messages"""
        self.running = False
    
    def save_to_file(self, filename: Optional[str] = None):
        """Save all received messages to a JSON file"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"mavlink_messages_{timestamp}.json"
        
        try:
            output_data = {
                'metadata': {
                    'start_time': self.start_time,
                    'end_time': time.time(),
                    'total_messages': self.message_count,
                    'unique_message_types': len(self.message_stats),
                    'connection_string': self.connection_string
                },
                'statistics': {
                    'message_counts': dict(self.message_stats),
                    'message_types': list(self.message_stats.keys())
                },
                'messages': self.all_messages
            }
            
            with open(filename, 'w') as f:
                json.dump(output_data, f, indent=2)
            
            print(f"[RECEIVER] Saved {self.message_count} messages to {filename}")
            return filename
            
        except Exception as e:
            print(f"[RECEIVER] Error saving to file: {e}")
            return None
    
    def print_final_stats(self):
        """Print final statistics"""
        if self.message_count == 0:
            print("[RECEIVER] No messages received")
            return
        
        runtime = time.time() - self.start_time if self.start_time else 0
        rate = self.message_count / runtime if runtime > 0 else 0
        
        print(f"\n[RECEIVER] FINAL STATISTICS")
        print(f"[RECEIVER] Total runtime: {runtime:.1f} seconds")
        print(f"[RECEIVER] Total messages: {self.message_count}")
        print(f"[RECEIVER] Average rate: {rate:.1f} messages/second")
        print(f"[RECEIVER] Unique message types: {len(self.message_stats)}")
        print(f"[RECEIVER] Unique messages: {len(self.unique_messages)}")
        
        print(f"\n[RECEIVER] Message type breakdown:")
        for msg_type, count in self.message_stats.most_common():
            percentage = (count / self.message_count) * 100
            print(f"  {msg_type}: {count} ({percentage:.1f}%)")
    
    def run(self):
        """Main run method - connect, receive, and cleanup"""
        try:
            # Connect to MAVProxy
            if not self.connect():
                return False
            
            # Start receiving messages
            self.start_receiving()
            
            return True
            
        except Exception as e:
            print(f"[RECEIVER] Error during execution: {e}")
            return False
        finally:
            # Cleanup
            self.stop()
            self.print_final_stats()
            
            # Save to file if requested
            if self.output_file or self.message_count > 0:
                self.save_to_file(self.output_file)
            
            self.disconnect()

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Receive and log ALL MAVLink messages from MAVProxy')
    parser.add_argument('--connection', default='udp:127.0.0.1:14550',
                       help='MAVLink connection string (default: udp:127.0.0.1:14550)')
    parser.add_argument('--output', default=None,
                       help='Output JSON file for all messages')
    parser.add_argument('--quiet', action='store_true',
                       help='Quiet mode - don\'t print messages to console')
    parser.add_argument('--duration', type=int, default=None,
                       help='Run for specified duration in seconds, then exit')
    
    args = parser.parse_args()
    
    # Create receiver
    receiver = MAVLinkMessageReceiver(
        connection_string=args.connection,
        output_file=args.output,
        verbose=not args.quiet
    )
    
    # Set duration if specified
    if args.duration:
        def duration_timer():
            time.sleep(args.duration)
            print(f"\n[RECEIVER] Duration of {args.duration} seconds reached, stopping...")
            receiver.stop()
        
        timer_thread = threading.Thread(target=duration_timer, daemon=True)
        timer_thread.start()
    
    try:
        # Run receiver
        success = receiver.run()
        return 0 if success else 1
        
    except KeyboardInterrupt:
        print("\n[RECEIVER] Interrupted by user")
        return 0
    except Exception as e:
        print(f"[RECEIVER] Fatal error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
