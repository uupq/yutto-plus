import asyncio
import argparse
import subprocess
import csv
import os
from bilibili_api import user # Keep user API for fetching lists
import toml
from pathlib import Path
from copy import deepcopy
import tempfile
import shutil
import re
import time
from datetime import datetime, timedelta
import platform
import sys
import json # Keep json for storing raw video info
import io # Needed for StringIO

# Global auto-answer flags
auto_yes = False
auto_no  = False

def get_confirmation(prompt: str) -> str:
    """
    Automatically returns 'y' or 'n' based on auto_yes/auto_no,
    otherwise calls built-in input().
    """
    if auto_yes:
        print(f"{prompt} y")   # Echo to console
        return 'y'
    if auto_no:
        print(f"{prompt} n")
        return 'n'
    # Ensure prompt ends with a space for clarity
    if not prompt.endswith(' '):
        prompt += ' '
    return input(prompt)


def truncate_long_values(d, max_length=500):
    """
    Recursively traverses a dictionary. If the string representation of a non-dict element
    exceeds max_length, it removes the element, except for 'title', 'duration', 'pages'.
    Args:
        d (dict): Input dictionary
        max_length (int): Maximum string length limit, default 500
    Returns:
        dict: Processed dictionary
    """
    result = {}
    for key, value in d.items():
        if isinstance(value, dict):
            result[key] = truncate_long_values(value, max_length)
        else:
            str_value = str(value)
            if len(str_value) <= max_length or key in ["title", "duration", "pages"]:
                result[key] = value
    return result


def extract_and_convert_time(input_str):
    """
    Extracts digits from a string representing seconds and converts to d/h/m/s format.
    """
    num_str = ''.join(char for char in input_str if char.isdigit())
    try:
        seconds = int(num_str)
    except ValueError:
        return "Invalid time"
    days = seconds // (24 * 3600)
    remaining_seconds = seconds % (24 * 3600)
    hours = remaining_seconds // 3600
    remaining_seconds %= 3600
    minutes = remaining_seconds // 60
    secs = remaining_seconds % 60
    result = ""
    if days > 0: result += f"{days}d"
    if hours > 0 or days > 0: result += f"{hours}h"
    if minutes > 0 or hours > 0 or days > 0: result += f"{minutes}m"
    result += f"{secs}s"
    # Handle case where duration is 0
    if not result: result = "0s"
    return result

def read_toml_config(file_path: str = os.path.join(os.getcwd(), "config.toml")) -> dict:
    """Reads configuration from a TOML file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            config_data = toml.load(f)
        if 'basic' not in config_data: config_data['basic'] = {}
        expected_keys = ["uid", "output_dir", "video_quality", "SESSDATA", "BILI_JCT", "BUVID3", "yutto_path"]
        for key in expected_keys:
            if key not in config_data['basic']: config_data['basic'][key] = ""
        return config_data
    except FileNotFoundError:
        print(f"Warning: Config file not found at {file_path}. Using defaults/command-line args.")
        return {"basic": {key: "" for key in ["uid", "output_dir", "video_quality", "SESSDATA", "BILI_JCT", "BUVID3", "yutto_path"]}}
    except toml.TomlDecodeError as e:
        print(f"Error: Invalid TOML format in {file_path}: {e}")
        raise
    except Exception as e:
        print(f"Unexpected error reading {file_path}: {e}")
        raise

async def get_video_info(bvid: str) -> dict:
    """Fetches video info using bilibili_api (Credentials likely not needed)."""
    from bilibili_api import video, Credential
    import asyncio
    credential = Credential(sessdata='', bili_jct='', buvid3='') # Blank credentials
    v = video.Video(bvid=bvid, credential=credential)
    max_attempts = 3 # Reduced attempts for info fetching
    for attempt in range(max_attempts):
        try:
            info = await v.get_info()
            return truncate_long_values(info)
        except Exception as e:
            error_msg = str(e)
            if "稿件不可见" in error_msg or "视频已失效" in error_msg or "404" in error_msg :
                 print(f"Video {bvid} is unavailable: {error_msg}")
                 return {"title": f"稿件不可见({bvid})", "duration": 0, "pages": []}
            if attempt < max_attempts - 1:
                wait_time = 2 ** attempt
                print(f"Attempt {attempt + 1}/{max_attempts} failed to get info for {bvid}: {error_msg}. Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                print(f"Failed to get video info for {bvid} after {max_attempts} attempts: {error_msg}")
                return {"title": f"获取信息失败({bvid})", "duration": 0, "pages": []}

async def get_user_name(uid: int) -> str:
    """Fetches the username for a given UID with retries."""
    max_attempts = 3
    base_wait_time = 2
    for attempt in range(max_attempts):
        try:
            u = user.User(uid)
            user_info = await u.get_user_info()
            return user_info["name"]
        except Exception as e:
            error_msg = str(e)
            wait_time = base_wait_time * (attempt + 1)
            if "风控校验失败" in error_msg: print(f"Attempt {attempt + 1}/{max_attempts} failed for UID {uid} due to risk control. Retrying in {wait_time}s...")
            elif '404' in error_msg: return f"用户不存在({uid})"
            elif '412' in error_msg: print(f"Attempt {attempt + 1}/{max_attempts} failed for UID {uid} due to 412 Precondition Failed. Retrying in {wait_time}s...")
            else: print(f"Attempt {attempt + 1}/{max_attempts} failed to get username for UID {uid}: {error_msg}. Retrying in {wait_time}s...")
            if attempt < max_attempts - 1: await asyncio.sleep(wait_time)
            else: return f"获取用户名失败({uid})"
    return f"获取用户名失败({uid})"

def get_file_names(output_dir: str, video_info: dict) -> list:
    """
    Constructs the expected output file path(s) based on video info.
    output_dir here is the *user-specific* directory (e.g., /path/123-User).
    """
    filenames = []
    safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', video_info.get('title', 'Untitled'))
    max_title_len = 100
    safe_title = safe_title[:max_title_len]
    pages = video_info.get('pages', [])
    if not pages: return [os.path.join(output_dir, f"{safe_title}.mp4")]
    if len(pages) == 1: return [os.path.join(output_dir, f"{safe_title}.mp4")]
    else:
        video_subfolder = os.path.join(output_dir, safe_title)
        for i, page in enumerate(pages):
             part_title = page.get('part', f'P{i+1}')
             safe_part_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', part_title)[:max_title_len]
             filenames.append(os.path.join(video_subfolder, f"{safe_part_title}.mp4"))
        return filenames

async def get_user_video_urls(uid: int, output_dir: str, updatefile: int = 0) -> list:
    """Gets all video URLs for a user, handling CSV loading/saving and updates (simplified)."""
    csv_path = Path(output_dir) / "video_urls.csv"
    video_urls = []
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    all_fieldnames = ['url', 'title', 'duration', 'downloaded', 'file_path', 'media_info', 'audio_info', 'info', 'error_info']
    required_fieldnames = ['url', 'title', 'duration', 'downloaded', 'file_path']

    if csv_path.exists():
        print(f"Reading existing video list from {csv_path}")
        last_save_time = None
        try:
            with open(csv_path, 'r', encoding='utf-8', newline='') as f:
                lines = f.readlines()
                # Find save time comment
                for line in lines:
                    if line.startswith('# SaveTime:'):
                        try:
                            # Attempt to parse the timestamp
                            last_save_time_str = line.strip().split('# SaveTime: ')[1]
                            last_save_time = datetime.strptime(last_save_time_str, '%Y-%m-%d %H:%M:%S')
                        except (IndexError, ValueError):
                            # Handle cases where splitting fails or parsing fails
                            print(f"Warning: Could not parse SaveTime: {line.strip()}")
                            last_save_time = None # Reset to None if parsing fails
                        break # Stop searching once the SaveTime line is found

                # Use io.StringIO for DictReader
                csv_content = io.StringIO("".join(line for line in lines if not line.startswith('#')))
                reader = csv.DictReader(csv_content)
                actual_fieldnames = reader.fieldnames
                if not actual_fieldnames:
                     print(f"Warning: CSV {csv_path} empty/no header. Fetching fresh list.")
                     return await fetch_and_save_new_list(uid, csv_path, all_fieldnames)
                missing_required = [f for f in required_fieldnames if f not in actual_fieldnames]
                if missing_required:
                    print(f"Error: CSV {csv_path} missing required fields: {missing_required}. Fix or delete.")
                    raise ValueError(f"CSV missing required fields: {missing_required}")
                video_urls = [{field: row.get(field, '') for field in all_fieldnames} for row in reader]
            print(f"Loaded {len(video_urls)} videos from CSV.")

            # --- Path Validation ---
            needs_resave = False
            for j, video in enumerate(video_urls):
                original_path_str = video.get('file_path', '')
                validated_paths = []
                try: file_paths_eval = eval(original_path_str) if original_path_str.startswith('[') and original_path_str.endswith(']') else [original_path_str]
                except: file_paths_eval = [original_path_str] # Fallback if eval fails
                paths_changed = False
                for file_path in file_paths_eval:
                    if isinstance(file_path, str) and file_path:
                        abs_file_path = os.path.abspath(file_path)
                        if os.path.exists(abs_file_path): validated_paths.append(abs_file_path)
                        else:
                            basename = os.path.basename(file_path)
                            potential_path_in_user_dir = os.path.join(output_dir, basename)
                            csv_title = video.get('title', '')
                            safe_csv_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', csv_title)[:100] if csv_title else ''
                            potential_path_in_subfolder = os.path.join(output_dir, safe_csv_title, basename) if safe_csv_title else ''
                            if os.path.exists(potential_path_in_user_dir): validated_paths.append(os.path.abspath(potential_path_in_user_dir)); paths_changed = True; print(f"  Path corrected for '{basename}' (found in user dir)")
                            elif potential_path_in_subfolder and os.path.exists(potential_path_in_subfolder): validated_paths.append(os.path.abspath(potential_path_in_subfolder)); paths_changed = True; print(f"  Path corrected for '{basename}' (found in subfolder '{safe_csv_title}')")
                            else: validated_paths.append(file_path) # Keep original if not found
                    elif file_path: validated_paths.append(str(file_path)) # Convert non-string to string
                new_path_str = str(validated_paths)
                if paths_changed: video_urls[j]['file_path'] = new_path_str; needs_resave = True
            if needs_resave: print("Updating CSV with corrected file paths."); save_to_csv(video_urls, csv_path, all_fieldnames)

            # --- Update Check Logic ---
            all_downloaded = all(str(v.get('downloaded')).lower() == 'true' for v in video_urls)
            perform_update_check = False
            if updatefile == 1: perform_update_check = True
            elif updatefile == -1: perform_update_check = False
            elif all_downloaded:
                if get_confirmation("All videos marked downloaded. Check for new videos? (y/n)").lower() == 'y': perform_update_check = True
            else:
                 if get_confirmation("Some videos not downloaded. Check for new videos too? (y/n)").lower() == 'y': perform_update_check = True
            if perform_update_check:
                if last_save_time and (datetime.now() - last_save_time) < timedelta(hours=12) and updatefile == 0 and not all_downloaded: print(f"CSV saved recently ({last_save_time}). Skipping online check.")
                else:
                    print("Checking for new videos online...")
                    try:
                        u = user.User(uid=uid); page = 1; online_videos = []
                        while True:
                            res = await u.get_videos(pn=page, ps=30)
                            if "list" not in res or "vlist" not in res["list"] or not res["list"]["vlist"]: break
                            vlist = res["list"]["vlist"]
                            for item in vlist:
                                if 'bvid' in item:
                                    new_entry = {f: '' for f in all_fieldnames}; new_entry['url'] = f"https://www.bilibili.com/video/{item['bvid']}"; new_entry['downloaded'] = 'False'; online_videos.append(new_entry)
                            if len(vlist) < 30: break
                            page += 1; await asyncio.sleep(0.5)
                        existing_urls = {v['url'] for v in video_urls}
                        new_videos = [v for v in online_videos if v['url'] not in existing_urls]
                        if new_videos: print(f"Found {len(new_videos)} new videos."); video_urls = new_videos + video_urls; save_to_csv(video_urls, csv_path, all_fieldnames)
                        else: print("No new videos found online."); save_to_csv(video_urls, csv_path, all_fieldnames) # Save to update timestamp
                    except Exception as e: print(f"Error fetching video list online for UID {uid}: {e}")
            return video_urls
        except Exception as e: print(f"Error reading/processing CSV {csv_path}: {e}. Fetching new list.")
    # Fetch new list if CSV doesn't exist or reading failed
    return await fetch_and_save_new_list(uid, csv_path, all_fieldnames)

async def fetch_and_save_new_list(uid: int, csv_path: Path, fieldnames: list) -> list:
     """Fetches the full video list from API and saves it to CSV."""
     video_urls = []
     try:
         u = user.User(uid=uid); page = 1
         print(f"Fetching initial video list for UID {uid} from Bilibili API...")
         while True:
             res = await u.get_videos(pn=page, ps=30)
             if "list" not in res or "vlist" not in res["list"] or not res["list"]["vlist"]: break
             vlist = res["list"]["vlist"]
             for item in vlist:
                  if 'bvid' in item:
                     new_entry = {f: '' for f in fieldnames}; new_entry['url'] = f"https://www.bilibili.com/video/{item['bvid']}"; new_entry['downloaded'] = 'False'; video_urls.append(new_entry)
             if len(vlist) < 30: break
             page += 1; await asyncio.sleep(0.5)
         print(f"Fetched total {len(video_urls)} video URLs from API.")
         save_to_csv(video_urls, csv_path, fieldnames)
         return video_urls
     except Exception as e: print(f"Error fetching initial list for UID {uid}: {e}"); save_to_csv([], csv_path, fieldnames); return []

def save_to_csv(video_urls: list, csv_path: Path, fieldnames: list):
    """Saves video information to CSV, updating save time only if content changes."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    video_urls_str = []
    for item in video_urls:
         # Ensure all values are strings, handle dict/list with json.dumps
         row = {field: (json.dumps(v) if isinstance(v := item.get(field, ''), (dict, list)) else str(v)) for field in fieldnames}
         video_urls_str.append(row)

    current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    last_save_time_str = None; existing_data_str = []; needs_write = True

    if csv_path.exists():
        try:
            with open(csv_path, 'r', encoding='utf-8', newline='') as f:
                lines = f.readlines()
                # Extract last save time
                for line in lines:
                    if line.startswith('# SaveTime:'):
                        try: last_save_time_str = line.strip().split('# SaveTime: ')[1]
                        except (IndexError, ValueError): pass # Ignore if format is wrong
                        break # Found the line
                # Read existing data using DictReader
                csv_content = io.StringIO("".join(line for line in lines if not line.startswith('#')))
                reader = csv.DictReader(csv_content)
                # Check if headers match expected fields before comparing data
                if reader.fieldnames and set(reader.fieldnames) == set(fieldnames):
                     existing_data_str = list(reader)
                else:
                     if reader.fieldnames: # Only warn if there was a header but it didn't match
                          print(f"Warning: Fieldnames mismatch in {csv_path}. Forcing rewrite.")
                     # If no header or mismatch, force rewrite by keeping existing_data_str empty

            # Compare data only if existing data was read successfully with matching headers
            if existing_data_str and len(existing_data_str) == len(video_urls_str):
                 # Compare row by row based on the defined fieldnames
                 data_identical = True
                 for old_row, new_row in zip(existing_data_str, video_urls_str):
                      # Compare only the fields we expect
                      if any(old_row.get(f, '') != new_row.get(f, '') for f in fieldnames):
                           data_identical = False
                           break
                 if data_identical:
                      needs_write = False
                      # print(f"CSV content for {csv_path.name} unchanged. Skipping write.")

        except Exception as e:
            print(f"Error reading existing CSV {csv_path} for comparison: {e}. Forcing rewrite.")
            existing_data_str = [] # Ensure rewrite on error

    if needs_write:
        print(f"Saving/Updating CSV file: {csv_path}")
        save_time_to_write = current_time_str; temp_file_path = None
        try:
            # Create temp file in the same directory to help with atomic move
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', delete=False, dir=csv_path.parent) as temp_file:
                temp_file_path = temp_file.name
                writer = csv.DictWriter(temp_file, fieldnames=fieldnames); writer.writeheader(); writer.writerows(video_urls_str)
                temp_file.write(f"\n# SaveTime: {save_time_to_write}\n"); temp_file.flush(); os.fsync(temp_file.fileno()) # Ensure write
            # Atomically replace the old file
            shutil.move(temp_file_path, csv_path); temp_file_path = None # Prevent deletion in finally
        except Exception as e:
            print(f"Error writing CSV to {csv_path}: {e}")
            # Clean up temp file if move failed
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except OSError as err:
                    print(f"Error deleting temp CSV {temp_file_path}: {err}")
            raise # Re-raise original error
        finally:
             # Double check for temp file cleanup
             if temp_file_path and os.path.exists(temp_file_path):
                  print(f"Warning: Temp file {temp_file_path} still exists.")
                  # Corrected Syntax Error Here:
                  try:
                      os.unlink(temp_file_path)
                  except OSError as err:
                      print(f"Error deleting lingering temp CSV {temp_file_path}: {err}")

def strip_ansi_codes(text):
    """Removes ANSI escape sequences from a string."""
    if not isinstance(text, str): return str(text)
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def download_video_simplified(url: str, user_output_dir: str, quality: str, sessdata: str, yutto_path: str, video_info: dict, timeout_seconds: int = 7200) -> tuple:
    """
    Downloads using yutto, showing real-time output directly. Success based on exit code.

    Args:
        url: Video URL.
        user_output_dir: User-specific base directory (e.g., /path/123-User).
        quality: Desired video quality string.
        sessdata: SESSDATA cookie value.
        yutto_path: Path to yutto executable.
        video_info: Video metadata dictionary.
        timeout_seconds: Timeout for waiting for yutto process to finish. Default 2 hours.

    Returns:
        tuple: (list_of_expected_paths, error_message_string)
    """
    print(f"--- Starting Download ---")
    print(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"URL: {url}")
    print(f"Output Dir (-d): {user_output_dir}") # Corrected: -d points here
    print(f"Quality: {quality}")

    expected_paths = get_file_names(user_output_dir, video_info)
    if not expected_paths:
        return [], "Could not determine expected output file paths."

    os.makedirs(user_output_dir, exist_ok=True)

    # --- Construct yutto command ---
    command = [
        yutto_path,
        "--sessdata", str(sessdata) if sessdata else "",
        "-d", user_output_dir, # Corrected: Use user_output_dir
        "-q", str(quality),
        "--save-cover",
        "--vip-strict",
        # Add '-b' flag ONLY if multiple pages
        *(["-b"] if len(video_info.get('pages', [])) > 1 else []),
        url
    ]
    command = [arg for arg in command if arg] # Remove empty args

    print(f"Executing Command: {' '.join(command)}")
    print("--- yutto Output Start ---") # Marker for where yutto output begins

    process = None
    error_message = ""
    return_code = -1 # Default to indicate failure

    try:
        # Execute yutto, inheriting stdout/stderr from this script's process
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            # stdout=None, # Inherit stdout (default) - No need to specify
            # stderr=None, # Inherit stderr (default) - No need to specify
        )

        # Wait for the process to complete with a timeout
        try:
            return_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            # Attempt to terminate gracefully first, then kill if necessary
            print(f"\n--- yutto process timed out after {timeout_seconds}s. Attempting termination... ---")
            process.terminate() # SIGTERM
            try:
                process.wait(timeout=10) # Wait a bit for graceful exit
            except subprocess.TimeoutExpired:
                print("--- Graceful termination failed. Killing process... ---")
                process.kill() # SIGKILL
                process.wait() # Ensure it's dead
            error_message = f"Error: yutto process timed out after {timeout_seconds} seconds and was terminated."
            print(error_message) # Print timeout error after yutto output
            return expected_paths, error_message

        print(f"--- yutto Process Finished (Exit Code: {return_code}) ---") # Marker for end

        # --- Check Success Based ONLY on Exit Code ---
        if return_code == 0:
            print(f"yutto exited successfully (Code 0). Assuming download complete for {url}.")
            # Optional: Verify file existence
            missing_files = []
            verified_paths = []
            for expected_path in expected_paths:
                 abs_path = os.path.abspath(expected_path)
                 if os.path.exists(abs_path) and os.path.getsize(abs_path) > 0: verified_paths.append(abs_path)
                 else: missing_files.append(os.path.basename(expected_path))
            if missing_files:
                 warn_msg = f"Warning: yutto exited 0 but expected file(s) missing/empty: {', '.join(missing_files)}"
                 print(warn_msg)
                 # error_message = warn_msg # Decide if this is an error

            return expected_paths, "" # Success

        else:
            # Failure case (non-zero exit code)
            error_message = f"Error: yutto exited with non-zero code: {return_code}."
            print(error_message) # Print error after yutto output
            # Cannot analyze stderr here as it went directly to terminal
            return expected_paths, error_message

    except FileNotFoundError:
        error_message = f"Error: '{yutto_path}' command not found. Install yutto or set yutto_path in config.toml."
        print(error_message)
        return expected_paths, error_message
    except Exception as e:
        error_message = f"Unexpected error launching/waiting for yutto: {e}"
        print(error_message)
        # Ensure process is terminated if it's still running after an exception
        if process and process.poll() is None:
             try: process.kill(); process.wait()
             except: pass # Ignore errors during cleanup
        return expected_paths, error_message


async def download_all_videos(arg_dict: dict, progress_callback=None, updatefile=0, username=None):
    """Main loop to download all videos (Simplified)."""
    uid = arg_dict.get("uid")
    base_output_dir = os.path.expanduser(arg_dict.get("output_dir", "~/Downloads/Bilibili"))
    quality = arg_dict.get("video_quality", "116")
    sessdata = arg_dict.get("SESSDATA", "")
    yutto_path = arg_dict.get("yutto_path", "yutto")

    if not uid: print("Error: UID missing."); return

    if not username:
        up_name = await get_user_name(uid)
        if f"失败({uid})" in up_name or f"不存在({uid})" in up_name: print(f"Could not get username for UID {uid}. Skipping."); return
    else: up_name = username

    safe_up_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', up_name)[:50]
    user_output_dir = os.path.join(base_output_dir, f"{uid}-{safe_up_name}")
    os.makedirs(user_output_dir, exist_ok=True)

    print(f"Processing UID: {uid} (UP: {safe_up_name}) | Output Dir: {user_output_dir}")

    video_list = await get_user_video_urls(uid, user_output_dir, updatefile=updatefile)
    csv_path = Path(user_output_dir) / "video_urls.csv"
    all_fieldnames = ['url', 'title', 'duration', 'downloaded', 'file_path', 'media_info', 'audio_info', 'info', 'error_info']

    if not video_list: print(f"No videos found for UID: {uid}."); return

    total_videos = len(video_list)
    print(f"Found {total_videos} videos in the list for {safe_up_name}.")
    error_log_file = Path(base_output_dir) / "download_errors.log"

    download_count = 0; skip_count = 0; fail_count = 0
    videos_to_process = [(i, v) for i, v in enumerate(video_list) if str(v.get('downloaded')).lower() != 'true']
    total_to_download = len(videos_to_process)
    already_downloaded_count = total_videos - total_to_download
    if already_downloaded_count > 0: print(f"{already_downloaded_count} videos already marked downloaded.")
    current_download_index = 0

    for i, video in videos_to_process:
        current_download_index += 1
        url = video.get('url')
        if not url: print(f"Skipping video #{i+1}/{total_videos} (missing URL)."); skip_count += 1; continue

        bvid = url.split("/")[-1].split("?")[0]

        print(f"\n[{current_download_index}/{total_to_download}] Getting info for video {i+1}/{total_videos}: {bvid}")
        video_info = await get_video_info(bvid=bvid)

        video['title'] = video_info.get('title', f'获取标题失败({bvid})')
        video['duration'] = extract_and_convert_time(str(video_info.get('duration', 0)))
        video['info'] = json.dumps(truncate_long_values(video_info, 150))
        video['error_info'] = ''

        if "稿件不可见" in video['title'] or not video_info.get('pages'):
            print(f"Skipping unavailable/invalid video {i+1}/{total_videos}: {video['title']} ({bvid})")
            video['downloaded'] = 'False'; video['error_info'] = "Video unavailable"; video['file_path'] = ''
            save_to_csv(video_list, csv_path, all_fieldnames); skip_count += 1; continue

        save_to_csv(video_list, csv_path, all_fieldnames) # Save updated info

        print(f"\n[{current_download_index}/{total_to_download}] Downloading video {i+1}/{total_videos}: {video['title']}")
        print(f"URL: {url} | Duration: {video['duration']}")

        duration_seconds = video_info.get('duration', 0)
        download_timeout = 1800 + duration_seconds * 5; max_timeout = 4 * 3600 # Timeout for process.wait()
        download_timeout = min(download_timeout, max_timeout)
        # print(f"Timeout (for reference): {download_timeout} seconds")

        max_attempts = 2; success = False; attempt = 0
        final_error_msg = ""; final_paths = []

        while attempt < max_attempts and not success:
            attempt += 1
            print(f"\nAttempt {attempt}/{max_attempts} for {bvid}")

            # Run simplified download in thread
            expected_paths, error_msg = await asyncio.to_thread(
                 download_video_simplified,
                 url, user_output_dir, quality, sessdata, yutto_path, video_info, download_timeout
            )
            final_error_msg = error_msg; final_paths = expected_paths

            if not error_msg: # Success (exit code 0)
                video['downloaded'] = 'True'
                verified_paths = [p for p in expected_paths if os.path.exists(p) and os.path.getsize(p) > 0]
                video['file_path'] = str(verified_paths if verified_paths else expected_paths)
                video['media_info'] = 'unknown'; video['audio_info'] = 'unknown'; video['error_info'] = ''
                save_to_csv(video_list, csv_path, all_fieldnames)
                success = True; download_count += 1
                # No need to print success message here, download_video_simplified already did
                break # Exit attempt loop
            else: # Failure
                # Error message already printed by download_video_simplified
                video['downloaded'] = 'False'; video['error_info'] = error_msg
                video['file_path'] = str(expected_paths); video['media_info'] = ''; video['audio_info'] = ''
                save_to_csv(video_list, csv_path, all_fieldnames)
                # Basic check if error seems unrecoverable based on message
                if "大会员" in error_msg or "付费内容" in error_msg or "不可见" in error_msg or "已失效" in error_msg or "timed out" in error_msg:
                     print("Stopping attempts due to likely unrecoverable error or timeout.")
                     break
                elif attempt < max_attempts:
                     wait_time = 10 * attempt; print(f"Waiting {wait_time}s..."); await asyncio.sleep(wait_time)

        if not success:
            fail_count += 1
            log_msg = f"Failed to download {url} ({video['title']}) after {max_attempts} attempts. Last error: {final_error_msg}"
            print(log_msg) # Print final failure summary
            try:
                with open(error_log_file, "a", encoding="utf-8") as lf:
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    lf.write(f"{timestamp} | UID: {uid} | BVID: {bvid} | Title: {video.get('title', 'N/A')} | Error: {final_error_msg}\n")
            except Exception as log_e: print(f"Warning: Could not write to error log {error_log_file}: {log_e}")

        await asyncio.sleep(1) # Delay between videos

    print("\n--- Download Summary ---")
    print(f"User: {safe_up_name} (UID: {uid})")
    print(f"Total videos in list: {total_videos}")
    print(f"Already downloaded: {already_downloaded_count}")
    print(f"Attempted to download: {total_to_download}")
    print(f"Processed successfully (Exit Code 0): {download_count}")
    print(f"Skipped (unavailable/URL error): {skip_count}")
    print(f"Failed after retries: {fail_count}")
    print(f"Error details logged to: {error_log_file}")
    print("------------------------")


# --- Functions for --update, --delete, --summarize remain largely the same ---

async def process_delete_path(delete_path: str, arg_dict: dict):
    """Handles the --delete operation."""
    abs_path = os.path.expanduser(delete_path)
    if not os.path.isdir(abs_path): 
        print(f"Error: --delete path '{abs_path}' not valid."); 
        return
    print(f"Scanning directory for deletion: {abs_path}")
    folders_to_process = []
    for item in os.listdir(abs_path):
        item_path = os.path.join(abs_path, item)
        if os.path.isdir(item_path):
            if re.match(r'^(\d+)-(.+)$', item) and os.path.exists(os.path.join(item_path, "video_urls.csv")):
                folders_to_process.append(item_path)
    if not folders_to_process: 
        print("No 'UID-Username' folders with 'video_urls.csv' found."); 
        return
    
    print("\nFolders targeted for content deletion (excluding video_urls.csv):")
    for folder in folders_to_process: 
        print(f"  - {os.path.basename(folder)}")
    
    print(f"\nWARNING: This will delete ALL files/subfolders EXCEPT 'video_urls.csv' in {len(folders_to_process)} folders.")
    response1 = input("Do you want to proceed? Type 'yes' to continue or anything else to cancel: ")
    if response1.lower() != 'yes': 
        print("Deletion canceled."); 
        return
        
    print("\n!!! FINAL WARNING !!!")
    print("This action CANNOT be undone. All video files and subfolders will be permanently deleted.")
    response2 = input("ARE YOU ABSOLUTELY SURE? Type 'DELETE' (in capital letters) to confirm: ")
    if response2 != 'DELETE': 
        print("Deletion canceled."); 
        return
    
    print("\nStarting deletion...")
    deleted_items_count = 0
    error_count = 0
    folders_with_content = 0
    folders_empty_except_csv = 0
    
    for folder in folders_to_process:
        print(f"Processing folder: {folder}")
        try:
            items = os.listdir(folder)
            print(f"  Found {len(items)} items in folder")
            
            # 统计除了CSV之外的项目
            non_csv_items = [item for item in items if item.lower() != "video_urls.csv"]
            if non_csv_items:
                folders_with_content += 1
                print(f"  Items to delete ({len(non_csv_items)}): {', '.join(non_csv_items[:5])}{'...' if len(non_csv_items) > 5 else ''}")
            else:
                folders_empty_except_csv += 1
                print(f"  No items to delete (only video_urls.csv found)")
                continue
            
            for item in items:
                item_path = os.path.join(folder, item)
                if item.lower() == "video_urls.csv": 
                    continue
                try:
                    # 检查路径是否实际存在
                    if not os.path.exists(item_path) and not os.path.islink(item_path):
                        print(f"  - Skipped non-existent item: {item}")
                        continue
                        
                    if os.path.isfile(item_path) or os.path.islink(item_path): 
                        os.unlink(item_path)
                        print(f"  - Deleted file: {item}")
                        deleted_items_count += 1
                    elif os.path.isdir(item_path): 
                        # 对于目录，使用强制删除
                        try:
                            shutil.rmtree(item_path)
                            print(f"  - Deleted folder: {item}")
                            deleted_items_count += 1
                        except OSError as dir_error:
                            # 如果shutil.rmtree失败，尝试递归强制删除
                            print(f"  - Trying force delete for folder: {item}")
                            try:
                                import subprocess
                                subprocess.run(['rm', '-rf', item_path], check=True)
                                print(f"  - Force deleted folder: {item}")
                                deleted_items_count += 1
                            except subprocess.CalledProcessError as force_error:
                                print(f"  - Error force deleting folder {item}: {force_error}")
                                error_count += 1
                    else:
                        # 如果无法确定类型，尝试删除
                        try:
                            os.unlink(item_path)
                            print(f"  - Deleted unknown item: {item}")
                            deleted_items_count += 1
                        except OSError:
                            print(f"  - Skipped unknown item type: {item}")
                except FileNotFoundError:
                    # 文件不存在，跳过
                    print(f"  - Skipped missing file: {item}")
                except OSError as e:
                    if e.errno == 2:  # No such file or directory
                        print(f"  - Skipped ghost file: {item}")
                    else:
                        print(f"  - Error deleting {item}: {e}")
                        error_count += 1
                except Exception as e: 
                    print(f"  - Error deleting {item}: {e}")
                    error_count += 1
        except Exception as e:
            print(f"  - Error accessing folder {folder}: {e}")
            error_count += 1
    
    print("\n--- Deletion Summary ---")
    print(f"Processed {len(folders_to_process)} folders total.")
    print(f"Folders with content to delete: {folders_with_content}")
    print(f"Folders with only video_urls.csv: {folders_empty_except_csv}")
    print(f"Items successfully deleted: {deleted_items_count}")
    if error_count > 0: 
        print(f"Encountered {error_count} errors.")
    print("------------------------")

def generate_summary_csv(base_output_dir: str):
    """Generates a summary CSV."""
    abs_path = os.path.expanduser(base_output_dir)
    if not os.path.isdir(abs_path): print(f"Error: Summary source '{abs_path}' not found."); return
    print(f"\nGenerating summary CSV from: {abs_path}")
    summary_data = []; processed_folders = 0
    all_fieldnames_summary = ['uid', 'username', 'url', 'title', 'duration', 'downloaded', 'file_path', 'media_info', 'audio_info', 'info', 'error_info']
    for item in os.listdir(abs_path):
        item_path = os.path.join(abs_path, item)
        if os.path.isdir(item_path):
            match = re.match(r'^(\d+)-(.+)$', item)
            if match:
                uid_str, username_in_folder = match.groups()
                csv_path = os.path.join(item_path, "video_urls.csv")
                if os.path.exists(csv_path):
                    processed_folders += 1; print(f"  - Reading: {csv_path.name} from {item}")
                    try:
                        with open(csv_path, 'r', encoding='utf-8', newline='') as f:
                             lines = f.readlines(); csv_content = io.StringIO("".join(l for l in lines if not l.startswith('#')))
                             reader = csv.DictReader(csv_content)
                             for row in reader:
                                  summary_row = {'uid': uid_str, 'username': username_in_folder}
                                  for field in all_fieldnames_summary: summary_row[field] = row.get(field, '')
                                  summary_data.append(summary_row)
                    except Exception as e: print(f"    Error reading {csv_path}: {e}")
    if not summary_data: print("No video data found to summarize."); return
    current_date = datetime.now().strftime('%Y%m%d')
    summary_csv_path = os.path.join(abs_path, f"summary-{current_date}.csv")
    print(f"\nWriting summary for {len(summary_data)} videos from {processed_folders} folders to: {summary_csv_path}")
    try:
        with open(summary_csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=all_fieldnames_summary); writer.writeheader(); writer.writerows(summary_data)
        print("Summary CSV generated.")
    except Exception as e: print(f"Error writing summary CSV {summary_csv_path}: {e}")

async def process_update_path(update_path: str, arg_dict: dict, summarize: bool = False):
    """Handles the --update operation."""
    abs_path = os.path.expanduser(update_path)
    if not os.path.isdir(abs_path): print(f"Error: --update path '{abs_path}' not valid."); return
    print(f"Scanning directory for updates: {abs_path}")
    folders_to_update = []
    for item in os.listdir(abs_path):
        item_path = os.path.join(abs_path, item)
        if os.path.isdir(item_path):
            if re.match(r'^(\d+)-(.+)$', item) and os.path.exists(os.path.join(item_path, "video_urls.csv")):
                folders_to_update.append(item_path)
    if not folders_to_update: print("No 'UID-Username' folders with 'video_urls.csv' found."); return
    print(f"\nFound {len(folders_to_update)} potential folders to update.")
    updated_count = 0; failed_updates = []
    for i, folder_path in enumerate(folders_to_update):
        print(f"\n--- Processing Folder {i+1}/{len(folders_to_update)}: {os.path.basename(folder_path)} ---")
        try:
            success = await update_folder(folder_path, arg_dict)
            if success: updated_count += 1
            if i < len(folders_to_update) - 1: sleep_time = 3; print(f"\nWaiting {sleep_time}s..."); await asyncio.sleep(sleep_time)
        except Exception as e: print(f"!! Error processing folder {folder_path}: {e}"); failed_updates.append(os.path.basename(folder_path))
    print("\n--- Update Operation Summary ---")
    print(f"Attempted update on {len(folders_to_update)} folders. Initiated processing for: {updated_count}.")
    if failed_updates: print(f"Failed due to errors: {len(failed_updates)} ({', '.join(failed_updates)})")
    print("-----------------------------")
    if summarize: generate_summary_csv(abs_path)

async def update_folder(folder_path: str, base_arg_dict: dict) -> bool:
    """Processes update for a single folder."""
    folder_name = os.path.basename(folder_path)
    match = re.match(r'^(\d+)-(.+)$', folder_name)
    if not match: return False
    uid_str, username_in_folder = match.groups(); uid = int(uid_str)
    csv_path = os.path.join(folder_path, "video_urls.csv")
    if not os.path.exists(csv_path): return False
    last_save_time = None
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('# SaveTime:'):
                    try: last_save_time = datetime.strptime(line.strip().split('# SaveTime: ')[1], '%Y-%m-%d %H:%M:%S');
                    except: pass
                    break
        if last_save_time and (datetime.now() - last_save_time) < timedelta(hours=12):
            hours_since_save = (datetime.now() - last_save_time).total_seconds() / 3600
            if get_confirmation(f"CSV in '{folder_name}' saved {hours_since_save:.1f}h ago. Update anyway? (y/n)").lower() != 'y': print(f"Skipping update for '{folder_name}' (recent save)."); return False
    except: pass # Ignore errors reading save time
    print(f"Validating username for UID {uid}...")
    actual_username = await get_user_name(uid)
    safe_actual_username = "获取失败"
    if f"失败({uid})" not in actual_username and f"不存在({uid})" not in actual_username: safe_actual_username = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', actual_username)[:50]
    else: safe_actual_username = username_in_folder
    original_folder_path = folder_path
    if safe_actual_username != username_in_folder and f"失败({uid})" not in actual_username:
        if get_confirmation(f"Username mismatch: Folder='{username_in_folder}', API='{safe_actual_username}'. Rename & Update? (y/n)").lower() == 'y':
            parent_dir = os.path.dirname(folder_path); new_folder_name = f"{uid}-{safe_actual_username}"; new_folder_path = os.path.join(parent_dir, new_folder_name)
            try:
                if not os.path.exists(new_folder_path): os.rename(folder_path, new_folder_path)
                else: print(f"Warning: Target '{new_folder_name}' exists. Updating existing.")
                folder_path = new_folder_path; print(f"Using folder: '{new_folder_name}'")
            except OSError as e: print(f"Error renaming '{folder_name}': {e}. Skipping."); return False
        else: print(f"Skipping update for '{folder_name}' (mismatch)."); return False
    current_arg_dict = base_arg_dict.copy()
    current_arg_dict["uid"] = uid; current_arg_dict["output_dir"] = os.path.dirname(original_folder_path) # Pass base dir
    print(f"Initiating update process for UID: {uid} (Username: {safe_actual_username})")
    await download_all_videos(arg_dict=current_arg_dict, updatefile=1, username=safe_actual_username) # Calls simplified download
    return True

def parse_arguments():
    """Parses command line arguments."""
    parser = argparse.ArgumentParser(description="Download Bilibili videos (Simplified).", formatter_class=argparse.RawTextHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-u", "--uid", type=str, help="Bilibili user UID(s), comma-separated.")
    group.add_argument("--update", action="store_true", help="Update 'UID-Username' folders in output dir.")
    group.add_argument("--delete", action="store_true", help="DANGER: Delete files (except CSV) in 'UID-Username' folders.")
    parser.add_argument("-o", "--output_dir", type=str, help="Base output directory (Default: config or ~/Downloads/Bilibili).")
    parser.add_argument("-q", "--video_quality", type=str, choices=["127", "126", "125", "120", "116", "112", "80", "74", "64", "32", "16"], help="Video quality code (Default: config or 116).")
    parser.add_argument("--summarize", action="store_true", help="Generate summary CSV after --update.")
    parser.add_argument('-y', '--yes', action='store_true', help="Auto-answer 'yes' (except --delete).")
    parser.add_argument('-n', '--no', action='store_true', help="Auto-answer 'no' (except --delete).")
    parser.add_argument('--sessdata', type=str, help="Bilibili SESSDATA cookie (Overrides config).")
    parser.add_argument('--yutto-path', type=str, default='/opt/homebrew/bin/yutto', help="Path to yutto executable (Overrides config.toml)")
    return parser.parse_args()

def main():
    """Main program entry point."""
    global auto_yes, auto_no
    script_dir = os.path.dirname(os.path.abspath(__file__)); config_path = os.path.join(script_dir, "config.toml")
    if not os.path.exists(config_path): config_path = os.path.join(os.getcwd(), "config.toml")
    toml_config = read_toml_config(config_path); config_basic = toml_config.get('basic', {})
    args = parse_arguments(); auto_yes = args.yes; auto_no = args.no
    if args.delete: auto_yes = auto_no = False # Safety for delete
    final_args = {}
    default_output_dir = os.path.expanduser("~/Downloads/Bilibili"); default_quality = "116"; default_yutto = "yutto"
    final_args["output_dir"] = args.output_dir or config_basic.get("output_dir") or default_output_dir
    final_args["video_quality"] = args.video_quality or config_basic.get("video_quality") or default_quality
    final_args["SESSDATA"] = args.sessdata or config_basic.get("SESSDATA") or ""
    final_args["yutto_path"] = getattr(args, 'yutto_path', None) or config_basic.get("yutto_path") or default_yutto
    try: os.makedirs(final_args["output_dir"], exist_ok=True)
    except OSError as e: print(f"Error creating base output dir '{final_args['output_dir']}': {e}"); sys.exit(1)

    if args.delete: print("--- Delete Operation ---"); asyncio.run(process_delete_path(final_args["output_dir"], final_args)); print("--- Delete Finished ---")
    elif args.update: print("--- Update Operation ---"); asyncio.run(process_update_path(final_args["output_dir"], final_args, summarize=args.summarize)); print("--- Update Finished ---")
    elif args.uid:
        print("--- Download Operation (Simplified - Direct Output) ---")
        uid_string = args.uid.replace('，', ',')
        try:
            uid_list = sorted(list(set(int(uid.strip()) for uid in uid_string.split(',') if uid.strip().isdigit())))
            if not uid_list: raise ValueError("No valid UIDs found.")
        except ValueError as e: print(f"Error: Invalid UID input '{args.uid}'. {e}"); sys.exit(1)
        print(f"Target UIDs: {', '.join(map(str, uid_list))}")
        print(f"Output Dir: {final_args['output_dir']}")
        print(f"Quality: {final_args['video_quality']}")
        print(f"Yutto Path: {final_args['yutto_path']}")
        print(f"SESSDATA Used: {'Yes' if final_args['SESSDATA'] else 'No'}")
        async def run_downloads():
             force_update_check = len(uid_list) > 1
             for i, uid in enumerate(uid_list):
                  current_arg_dict = final_args.copy(); current_arg_dict["uid"] = uid
                  print(f"\n>>> Processing UID {i+1}/{len(uid_list)}: {uid}")
                  # Call the main download function
                  await download_all_videos(arg_dict=current_arg_dict, updatefile=1 if force_update_check else 0)
                  if i < len(uid_list) - 1: await asyncio.sleep(3) # Short delay between users
        asyncio.run(run_downloads())
        print("\n--- All Download Tasks Finished ---")
    else: print("Error: No operation specified (-u, --update, --delete)."); sys.exit(1)

if __name__ == "__main__":
    main()
