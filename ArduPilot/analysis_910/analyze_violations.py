#!/usr/bin/env python3
"""
Analyze policy violation files to understand their content and structure
"""

import os
import glob
import json
from collections import defaultdict, Counter
from typing import Dict, List, Tuple

def analyze_violation_files(violations_dir: str = "policy_violations910") -> Dict:
    """Analyze all violation files and return statistics"""
    
    print(f"[ANALYZER] Analyzing violation files in {violations_dir}")
    
    # Get all violation files
    violation_files = glob.glob(os.path.join(violations_dir, "*.txt"))
    violation_files.sort()
    
    print(f"[ANALYZER] Found {len(violation_files)} violation files")
    
    # Statistics
    stats = {
        'total_files': len(violation_files),
        'files_with_content': 0,
        'total_commands': 0,
        'command_types': Counter(),
        'parameter_names': Counter(),
        'command_names': Counter(),
        'environmental_factors': Counter(),
        'files_by_command_count': defaultdict(int),
        'empty_files': [],
        'sample_commands': []
    }
    
    # Analyze each file
    for i, filepath in enumerate(violation_files):
        filename = os.path.basename(filepath)
        
        try:
            with open(filepath, 'r') as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
            
            if not lines:
                stats['empty_files'].append(filename)
                continue
            
            stats['files_with_content'] += 1
            stats['total_commands'] += len(lines)
            stats['files_by_command_count'][len(lines)] += 1
            
            # Analyze each command
            for line in lines:
                parts = line.split(' ', 2)
                if len(parts) < 2:
                    continue
                
                cmd_type = parts[0]
                cmd_name = parts[1]
                cmd_value = parts[2] if len(parts) > 2 else ""
                
                stats['command_types'][cmd_type] += 1
                
                if cmd_type == 'P':  # Parameter
                    stats['parameter_names'][cmd_name] += 1
                elif cmd_type == 'C':  # Command
                    stats['command_names'][cmd_name] += 1
                elif cmd_type == 'E':  # Environmental
                    stats['environmental_factors'][cmd_name] += 1
                
                # Collect sample commands
                if len(stats['sample_commands']) < 20:
                    stats['sample_commands'].append({
                        'file': filename,
                        'command': line
                    })
            
        except Exception as e:
            print(f"[ANALYZER] Error analyzing {filename}: {e}")
    
    return stats

def print_analysis(stats: Dict):
    """Print analysis results"""
    
    print(f"\n[ANALYZER] ANALYSIS RESULTS")
    print(f"[ANALYZER] Total files: {stats['total_files']}")
    print(f"[ANALYZER] Files with content: {stats['files_with_content']}")
    print(f"[ANALYZER] Empty files: {len(stats['empty_files'])}")
    print(f"[ANALYZER] Total commands: {stats['total_commands']}")
    
    if stats['total_commands'] > 0:
        avg_commands = stats['total_commands'] / stats['files_with_content']
        print(f"[ANALYZER] Average commands per file: {avg_commands:.1f}")
    
    print(f"\n[ANALYZER] Command types:")
    for cmd_type, count in stats['command_types'].most_common():
        percentage = (count / stats['total_commands']) * 100
        print(f"[ANALYZER]   {cmd_type}: {count} ({percentage:.1f}%)")
    
    print(f"\n[ANALYZER] Top 10 parameters:")
    for param, count in stats['parameter_names'].most_common(10):
        print(f"[ANALYZER]   {param}: {count}")
    
    print(f"\n[ANALYZER] Top 10 commands:")
    for cmd, count in stats['command_names'].most_common(10):
        print(f"[ANALYZER]   {cmd}: {count}")
    
    print(f"\n[ANALYZER] Top 10 environmental factors:")
    for env, count in stats['environmental_factors'].most_common(10):
        print(f"[ANALYZER]   {env}: {count}")
    
    print(f"\n[ANALYZER] Files by command count:")
    for cmd_count, file_count in sorted(stats['files_by_command_count'].items()):
        print(f"[ANALYZER]   {cmd_count} commands: {file_count} files")
    
    if stats['empty_files']:
        print(f"\n[ANALYZER] Empty files (first 10):")
        for filename in stats['empty_files'][:10]:
            print(f"[ANALYZER]   {filename}")
        if len(stats['empty_files']) > 10:
            print(f"[ANALYZER]   ... and {len(stats['empty_files']) - 10} more")
    
    print(f"\n[ANALYZER] Sample commands:")
    for sample in stats['sample_commands'][:10]:
        print(f"[ANALYZER]   {sample['file']}: {sample['command']}")

def save_analysis(stats: Dict, filename: str = "violation_analysis.json"):
    """Save analysis to JSON file"""
    try:
        # Convert Counter objects to regular dicts for JSON serialization
        json_stats = {}
        for key, value in stats.items():
            if isinstance(value, Counter):
                json_stats[key] = dict(value)
            elif isinstance(value, defaultdict):
                json_stats[key] = dict(value)
            else:
                json_stats[key] = value
        
        with open(filename, 'w') as f:
            json.dump(json_stats, f, indent=2)
        
        print(f"[ANALYZER] Analysis saved to {filename}")
        
    except Exception as e:
        print(f"[ANALYZER] Error saving analysis: {e}")

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Analyze policy violation files')
    parser.add_argument('--violations-dir', default='policy_violations910',
                       help='Directory containing violation files')
    parser.add_argument('--output', default='violation_analysis.json',
                       help='Output filename for analysis')
    
    args = parser.parse_args()
    
    # Analyze violations
    stats = analyze_violation_files(args.violations_dir)
    
    # Print and save results
    print_analysis(stats)
    save_analysis(stats, args.output)

if __name__ == "__main__":
    main()
