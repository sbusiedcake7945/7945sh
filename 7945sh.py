import os
import sys
import subprocess
import atexit
import shutil
import signal
import glob
import re
import datetime
import warnings
from pathlib import Path

# Disable deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.lexers import Lexer
    from prompt_toolkit.styles import Style
    from prompt_toolkit.formatted_text import ANSI
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    import readline
    HAS_PROMPT_TOOLKIT = False

COLORS = {
    "BLUE": "\x1b[38;5;45m", "CYAN": "\x1b[38;5;51m",
    "RED": "\x1b[31m", "GREEN": "\x1b[32m", "YELLOW": "\x1b[33m",
    "MAGENTA": "\x1b[35m", "WHITE": "\x1b[37m", "GRAY": "\x1b[90m",
    "ORANGE": "\x1b[38;5;208m", "PURPLE": "\x1b[38;5;135m",
    "RESET": "\x1b[0m", "BOLD": "\x1b[1m", "DIM": "\x1b[2m"
}

SYNTAX_COLORS = {
    'string': COLORS['GREEN'], 'command': COLORS['GREEN'],
    'argument': COLORS['YELLOW'], 'variable': COLORS['MAGENTA'],
    'number': COLORS['PURPLE'], 'comment': COLORS['GRAY'],
    'operator': COLORS['ORANGE'], 'path': COLORS['BLUE']
}

DEFAULT_RC = """# 7945sh RC
PROMPT="{GREEN}{user}@{host}:{BLUE}{path}{RESET}$"
BLUE=\\x1b[38;5;45m
CYAN=\\x1b[38;5;51m
RED=\\x1b[31m
GREEN=\\x1b[32m
YELLOW=\\x1b[33m
RESET=\\x1b[0m
alias ls=ls --color=auto
alias ll=ls -la
alias la=ls -A
alias grep=grep --color=auto
alias cp=cp -i
alias mv=mv -i
alias rm=rm -i
alias ..=cd ..
alias ...=cd ../..
"""

AUTOCORRECT_DICT = {
    'sl': 'ls', 'gerp': 'grep', 'fidn': 'find', 'exot': 'exit',
    'cd..': 'cd ..', 'mkdie': 'mkdir', 'ehco': 'echo',
    'pythno': 'python', 'pyhton': 'python', 'gi': 'git',
    'gti': 'git', 'nvmi': 'nvim', 'vpip': 'pip', 'cta': 'cat'
}

histfile = os.path.expanduser("~/.7945sh_history")
default_rc = os.path.expanduser("~/.7945shrc")
current_process = None
app_aliases = {}
app_config = {**COLORS, "PROMPT": "{CYAN}┌─[{BLUE}{user}{CYAN}]─({BLUE}{path}{CYAN}){RESET}\n{CYAN}└─╼ {RESET}"}
binary_cache = set()
syntax_highlight = True
autocorrect_enabled = True

# Open /dev/tty directly so subprocess I/O always hits the real TTY device,
# bypassing any Python or prompt_toolkit output interception.
# This is required for Sixel, Kitty graphics protocol, fastfetch images, etc.
try:
    _tty_fd = os.open("/dev/tty", os.O_RDWR)
    _tty_r_fd = _tty_fd
    _tty_w_fd = os.dup(_tty_fd)
except OSError:
    _tty_r_fd = sys.__stdin__.fileno()
    _tty_w_fd = sys.__stdout__.fileno()


def levenshtein(s1, s2):
    if len(s1) < len(s2): return levenshtein(s2, s1)
    if len(s2) == 0: return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j+1]+1, curr[j]+1, prev[j]+(c1!=c2)))
        prev = curr
    return prev[-1]

def wrap_ansi(text):
    parts = []
    last_end = 0
    for match in re.finditer(r'\x1b\[[0-9;]*m', text):
        start, end = match.span()
        parts.append(text[last_end:start])
        parts.append('\x01' + match.group() + '\x02')
        last_end = end
    parts.append(text[last_end:])
    return ''.join(parts)

def safe_decode(val):
    try: return val.encode().decode('unicode_escape')
    except: return val

def create_default_rc():
    if not os.path.exists(default_rc):
        with open(default_rc, 'w') as f:
            f.write(DEFAULT_RC)
    return default_rc

def cache_binaries():
    global binary_cache
    binary_cache.clear()
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if os.path.isdir(p):
            try:
                for item in os.listdir(p):
                    if os.access(os.path.join(p, item), os.X_OK):
                        binary_cache.add(item)
            except PermissionError: continue

def sigint_handler(signum, frame):
    global current_process
    if current_process:
        try:
            current_process.send_signal(signal.SIGINT)
        except: pass
    else: print()

signal.signal(signal.SIGINT, sigint_handler)

def convert_shell_prompt(prompt_str):
    if not prompt_str: return prompt_str
    prompt_str = re.sub(r'^export\s+', '', prompt_str)
    
    # Zsh prompt converter
    prompt_str = prompt_str.replace('%n', '{user}')
    prompt_str = prompt_str.replace('%m', '{host}')
    prompt_str = prompt_str.replace('%M', '{host}')
    prompt_str = prompt_str.replace('%~', '{path}')
    prompt_str = prompt_str.replace('%d', '{path}')
    prompt_str = prompt_str.replace('%/', '{path}')
    prompt_str = prompt_str.replace('%B', '{BOLD}')
    prompt_str = prompt_str.replace('%b', '{RESET}')
    prompt_str = prompt_str.replace('%f', '{RESET}')
    
    def zsh_color(match):
        color = match.group(1).lower()
        if color in ('green', 'blue', 'red', 'cyan', 'yellow', 'magenta', 'white', 'reset'):
            return '{' + color.upper() + '}'
        if color.isdigit():
            return f'\x1b[38;5;{color}m'
        return ''
    prompt_str = re.sub(r'%F\{([^}]+)\}', zsh_color, prompt_str)
    
    # Bash prompt converter
    prompt_str = prompt_str.replace(r'\u', '{user}')
    prompt_str = prompt_str.replace(r'\h', '{host}')
    prompt_str = prompt_str.replace(r'\w', '{path}')
    prompt_str = prompt_str.replace(r'\W', '{path}')
    prompt_str = prompt_str.replace(r'\e', '\x1b')
    prompt_str = prompt_str.replace(r'\033', '\x1b')
    prompt_str = prompt_str.replace(r'\[', '')
    prompt_str = prompt_str.replace(r'\]', '')
    
    return prompt_str

def load_rc(rc_path=None, run_foreground=False):
    global app_aliases, app_config, syntax_highlight, autocorrect_enabled
    if rc_path is None: rc_path = create_default_rc()
    else: rc_path = os.path.expanduser(rc_path)
    if not os.path.isfile(rc_path): return
    
    # Detect shell type
    shell_cmd = 'sh'
    with open(rc_path, 'r', errors='ignore') as f:
        try: first_line = f.readline().strip()
        except: first_line = ""
        
    if first_line.startswith("#!"):
        shell_cmd = first_line[2:].strip()
    elif rc_path.endswith(('zshrc', '.zsh', 'zprofile')) or 'zsh' in shell_cmd_fallback(rc_path):
        shell_cmd = 'zsh'
    elif rc_path.endswith(('bashrc', '.bash', 'bash_profile', '.sh')) or 'bash' in shell_cmd_fallback(rc_path):
        shell_cmd = 'bash'
        
    # Execute the file in the foreground first so visual/printed output (ASCII art, fastfetch, lolcat) displays immediately
    if run_foreground:
        try:
            subprocess.run([shell_cmd, "-c", f"source {rc_path}"], stdin=sys.__stdin__, stdout=sys.__stdout__, stderr=sys.__stderr__)
        except:
            pass

    if shell_cmd:
        try:
            # Source file and get aliases & variables silently
            run_cmd = [shell_cmd, "-c", f"source {rc_path} && alias && echo '===PROMPT===' && echo \"PROMPT=$PROMPT\" && echo \"PS1=$PS1\""]
            result = subprocess.run(run_cmd, capture_output=True, text=True, timeout=3, errors='ignore')
            if result.returncode == 0:
                in_prompt = False
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line == '===PROMPT===':
                        in_prompt = True
                        continue
                    if not in_prompt:
                        if line.startswith('alias '):
                            line = line[6:].strip()
                        if '=' in line:
                            name, val = line.split('=', 1)
                            app_aliases[name.strip()] = safe_decode(val.strip().strip("'\""))
                    else:
                        if '=' in line:
                            key, val = line.split('=', 1)
                            key = key.strip()
                            val = safe_decode(val.strip().strip("'\""))
                            if val:
                                app_config[key] = convert_shell_prompt(val)
        except:
            pass

    # Manual fallback parser for non-interactive custom variables
    try:
        with open(rc_path, 'r', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'): continue
                if line.startswith('export '):
                    line = line[7:].strip()
                if line.startswith('alias '):
                    parts = line[6:].split('=', 1)
                    if len(parts) == 2:
                        app_aliases[parts[0].strip()] = safe_decode(parts[1].strip().strip("'\""))
                elif '=' in line:
                    key, val = line.split('=', 1)
                    key, val = key.strip(), safe_decode(val.strip().strip("'\""))
                    if key == 'SYNTAX_HIGHLIGHT': syntax_highlight = val.lower() == 'true'
                    elif key == 'AUTOCORRECT': autocorrect_enabled = val.lower() == 'true'
                    else: app_config[key] = convert_shell_prompt(val)
    except:
        pass

def shell_cmd_fallback(path):
    path_lower = path.lower()
    if 'zsh' in path_lower: return 'zsh'
    if 'bash' in path_lower: return 'bash'
    return ''

def is_valid_command(cmd_name):
    if cmd_name in app_aliases: return True
    if cmd_name in binary_cache: return True
    if cmd_name in ('exit', 'quit', 'cd', 'source'): return True
    if os.path.exists(cmd_name) and os.access(cmd_name, os.X_OK): return True
    return False

def highlight_syntax(text):
    if not syntax_highlight or not text: return text
    
    # Isolate comments
    if '#' in text:
        code_part, comment_part = text.split('#', 1)
        comment_part = '#' + comment_part
    else:
        code_part, comment_part = text, ''
        
    parts = code_part.split()
    if not parts: 
        return f"{SYNTAX_COLORS['comment']}{comment_part}{COLORS['RESET']}" if comment_part else text
    
    command = parts[0]
    args = ' '.join(parts[1:]) if len(parts) > 1 else ''
    
    if is_valid_command(command):
        highlighted_cmd = f"{SYNTAX_COLORS['command']}{command}{COLORS['RESET']}"
    else:
        highlighted_cmd = f"{COLORS['RED']}{command}{COLORS['RESET']}"
    
    if args:
        highlighted_args = args
        highlighted_args = re.sub(r'(".*?"|\'.*?\')', 
                                  lambda m: f"{SYNTAX_COLORS['string']}{m.group(0)}{COLORS['RESET']}", 
                                  highlighted_args)
        highlighted_args = re.sub(r'\s(-\w+|--\w[\w-]*)', 
                                  lambda m: f" {SYNTAX_COLORS['argument']}{m.group(1)}{COLORS['RESET']}", 
                                  highlighted_args)
        highlighted_args = re.sub(r'\$[\w]+|\${[\w]+}', 
                                  lambda m: f"{SYNTAX_COLORS['variable']}{m.group(0)}{COLORS['RESET']}", 
                                  highlighted_args)
        highlighted_args = re.sub(r'\b\d+(\.\d+)?\b', 
                                  lambda m: f"{SYNTAX_COLORS['number']}{m.group(0)}{COLORS['RESET']}", 
                                  highlighted_args)
        highlighted_args = re.sub(r'[~/\.]+\S*', 
                                  lambda m: f"{SYNTAX_COLORS['path']}{m.group(0)}{COLORS['RESET']}", 
                                  highlighted_args)
        highlighted_args = re.sub(r'([|&;<>])', 
                                  lambda m: f"{SYNTAX_COLORS['operator']}{m.group(0)}{COLORS['RESET']}", 
                                  highlighted_args)
        res = f"{highlighted_cmd} {highlighted_args}"
    else:
        res = highlighted_cmd
        
    if comment_part:
        res += f" {SYNTAX_COLORS['comment']}{comment_part}{COLORS['RESET']}"
    return res

def autocorrect(cmd):
    if not autocorrect_enabled or not cmd: return cmd
    
    parts = cmd.split()
    if not parts: return cmd
    
    cmd_name = parts[0].lower()
    
    if is_valid_command(cmd_name):
        return cmd
    
    if cmd_name in AUTOCORRECT_DICT:
        corrected = AUTOCORRECT_DICT[cmd_name]
        print(f"{COLORS['YELLOW']}7945sh: '{cmd_name}' not found, corrected to '{corrected}'{COLORS['RESET']}")
        parts[0] = corrected
        return ' '.join(parts)
    
    best, best_dist = None, float('inf')
    cmd_len = len(cmd_name)
    for bin_cmd in binary_cache:
        # Celeron N4500 performance filter
        if abs(len(bin_cmd) - cmd_len) > 2:
            continue
        dist = levenshtein(cmd_name, bin_cmd)
        if dist < best_dist and dist <= 2:
            best_dist, best = dist, bin_cmd
    
    if best:
        print(f"{COLORS['YELLOW']}7945sh: '{cmd_name}' not found, did you mean '{best}'?{COLORS['RESET']}")
        parts[0] = best
        return ' '.join(parts)
    
    return cmd

def make_prompt(wrap_ansi_codes=True):
    template = app_config.get("PROMPT", app_config.get("PS1", "{user}@{host}:{path}$ "))
    data = {
        "user": os.environ.get("USER", "7945"),
        "host": os.uname()[1],
        "path": os.getcwd().replace(os.path.expanduser("~"), "~"),
        "time": datetime.datetime.now().strftime("%H:%M:%S"),
        **app_config
    }
    processed = {}
    for k, v in data.items():
        if isinstance(v, str) and "\x1b[" in v:
            processed[k] = wrap_ansi(v) if wrap_ansi_codes else v
        else:
            processed[k] = v
    try: return template.format(**processed)
    except:
        clean_template = template.replace("$", "")
        try: return clean_template.format(**processed)
        except: return f"{data['user']}@{data['host']}:{data['path']}$ "

# --- PROMPT TOOLKIT INTEGRATION ---
if HAS_PROMPT_TOOLKIT:
    class ShellLexer(Lexer):
        def lex_document(self, document):
            def get_line(lineno):
                text = document.lines[lineno]
                if not text:
                    return []
                
                # Split code and comments
                if '#' in text:
                    code_part, comment_part = text.split('#', 1)
                    comment_part = '#' + comment_part
                else:
                    code_part, comment_part = text, ''
                
                raw_parts = re.split(r'(\s+)', code_part)
                tokens = []
                is_first_word = True
                
                for part in raw_parts:
                    if not part:
                        continue
                    if part.isspace():
                        tokens.append(('', part))
                        continue
                    
                    if is_first_word:
                        is_first_word = False
                        if is_valid_command(part):
                            tokens.append(('class:command', part))
                        else:
                            tokens.append(('class:invalid_command', part))
                        continue
                        
                    if part.startswith(('"', "'")):
                        tokens.append(('class:string', part))
                    elif part.startswith('-'):
                        tokens.append(('class:argument', part))
                    elif part.startswith('$'):
                        tokens.append(('class:variable', part))
                    elif part.isdigit():
                        tokens.append(('class:number', part))
                    elif any(c in part for c in ('/', '.', '~')):
                        tokens.append(('class:path', part))
                    elif any(c in part for c in ('|', '&', ';', '<', '>')):
                        tokens.append(('class:operator', part))
                    else:
                        tokens.append(('class:argument', part))
                
                if comment_part:
                    tokens.append(('class:comment', comment_part))
                return tokens
            return get_line

    class ShellCompleter(Completer):
        def get_completions(self, document, complete_event):
            word = document.get_word_before_cursor(WORD=True)
            before_cursor = document.text_before_cursor
            is_command = len(before_cursor.lstrip().split()) <= 1 and not before_cursor.endswith(' ')
            
            search_path = word
            if search_path.startswith('~'):
                search_path = os.path.expanduser(search_path)
                
            if is_command:
                for cmd in binary_cache:
                    if cmd.startswith(word):
                        yield Completion(cmd, start_position=-len(word))
                try:
                    for m in glob.glob(search_path + "*"):
                        if os.access(m, os.X_OK) or os.path.isdir(m):
                            display_name = m
                            if word.startswith('~'):
                                display_name = m.replace(os.path.expanduser('~'), '~', 1)
                            if os.path.isdir(m) and not display_name.endswith('/'):
                                display_name += '/'
                            yield Completion(display_name, start_position=-len(word))
                except:
                    pass
            else:
                try:
                    for m in glob.glob(search_path + "*"):
                        display_name = m
                        if word.startswith('~'):
                            display_name = m.replace(os.path.expanduser('~'), '~', 1)
                        if os.path.isdir(m) and not display_name.endswith('/'):
                            display_name += '/'
                        yield Completion(display_name, start_position=-len(word))
                except:
                    pass

    shell_style = Style.from_dict({
        'command': '#00ff5f bold',
        'invalid_command': '#ff005f bold',
        'string': '#ffd700',
        'argument': '#00afd7',
        'variable': '#ff00ff',
        'number': '#af87ff',
        'path': '#5fafff',
        'operator': '#ff8700',
        'comment': '#808080 italic',
    })

# --- READLINE FALLBACK ---
def completer_readline(text, state):
    line = readline.get_line_buffer()
    search_path = text
    if search_path.startswith('~'):
        search_path = os.path.expanduser(search_path)
        
    before_cursor = line[:readline.get_begidx()]
    is_command = len(before_cursor.strip()) == 0
    
    matches = []
    if is_command:
        matches = [c for c in binary_cache if c.startswith(text)]
        local_matches = glob.glob(search_path + "*")
        for m in local_matches:
            if os.access(m, os.X_OK) or os.path.isdir(m):
                if text.startswith('~'):
                    m = m.replace(os.path.expanduser('~'), '~', 1)
                matches.append(m)
    else:
        local_matches = glob.glob(search_path + "*")
        for m in local_matches:
            if text.startswith('~'):
                m = m.replace(os.path.expanduser('~'), '~', 1)
            matches.append(m)
            
    matches = sorted(list(set(matches)))
    
    final_matches = []
    for m in matches:
        real_path = os.path.expanduser(m) if m.startswith('~') else m
        if os.path.isdir(real_path):
            if not m.endswith('/'):
                final_matches.append(m + '/')
            else:
                final_matches.append(m)
        else:
            final_matches.append(m)
            
    if state < len(final_matches):
        return final_matches[state]
    return None

def execute_command(raw_cmd):
    global current_process
    cmd = os.path.expandvars(raw_cmd)
    cmd = autocorrect(cmd)
    
    parts = cmd.split()
    if not parts: return
    cmd_name = parts[0]

    if cmd_name in app_aliases:
        cmd = app_aliases[cmd_name] + cmd[len(cmd_name):]
        parts = cmd.split()
        if parts: cmd_name = parts[0]

    if cmd_name in ("exit", "quit"):
        sys.exit(0)
    elif cmd_name == "cd":
        target = parts[1] if len(parts) > 1 else "~"
        try: os.chdir(os.path.expanduser(target))
        except Exception as e: print(f"{COLORS['RED']}cd error: {e}{COLORS['RESET']}")
    elif cmd_name == "source":
        target = parts[1] if len(parts) > 1 else default_rc
        load_rc(target, run_foreground=True)
        cache_binaries()
        print(f"{COLORS['CYAN']}7945sh: {target} loaded.{COLORS['RESET']}")
    elif cmd_name in ("clear", "cls"):
        # Write directly to the real TTY fd
        os.write(_tty_w_fd, b"\033[H\033[2J")
    else:
        try:
            # Pass raw /dev/tty fd integers to Popen.
            # This ensures subprocesses (fastfetch, catimg, viu, etc.) get a real
            # isatty()-passing fd so they enable graphics/color output.
            # TERM is set so tools detect the terminal correctly.
            env = os.environ.copy()
            env.setdefault("TERM", "xterm-256color")
            current_process = subprocess.Popen(
                cmd,
                shell=True,
                stdin=_tty_r_fd,
                stdout=_tty_w_fd,
                stderr=_tty_w_fd,
                env=env
            )
            current_process.wait()
        except Exception as e:
            print(f"{COLORS['RED']}7945sh: {e}{COLORS['RESET']}")
        finally:
            current_process = None

def repl():
    global current_process
    
    # Pre-load config & cache (run foreground to show any startup logo/ASCII banner)
    load_rc(run_foreground=True)
    cache_binaries()

    if HAS_PROMPT_TOOLKIT:
        session = PromptSession(
            history=FileHistory(histfile),
            auto_suggest=AutoSuggestFromHistory(),
            completer=ShellCompleter(),
            lexer=ShellLexer(),
            style=shell_style
        )
        
        while True:
            try:
                prompt_str = make_prompt(wrap_ansi_codes=False)
                raw_cmd = session.prompt(ANSI(prompt_str)).strip()
            except EOFError:
                print("^C")
                break
            except KeyboardInterrupt:
                print(); continue

            if not raw_cmd or raw_cmd.startswith('#'): continue
            # After session.prompt() returns, prompt_toolkit has already
            # yielded TTY control back to us. Direct call is safe and correct.
            execute_command(raw_cmd)
    else:
        try:
            if os.path.exists(histfile): readline.read_history_file(histfile)
        except: pass
        atexit.register(readline.write_history_file, histfile)

        readline.set_completer(completer_readline)
        readline.set_completer_delims(" \t\n\"\\'`@$><=;|&{(")
        readline.parse_and_bind("tab: complete")

        while True:
            try:
                prompt_str = make_prompt(wrap_ansi_codes=True)
                raw_cmd = input(prompt_str).strip()
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print(); continue

            if not raw_cmd or raw_cmd.startswith('#'): continue
            
            if syntax_highlight:
                prompt_lines = prompt_str.split('\n')
                num_lines = len(prompt_lines)
                cleanup = ""
                for _ in range(num_lines):
                    cleanup += "\033[1A\033[2K"
                cleanup += "\r"
                print(f"{cleanup}{prompt_str}{highlight_syntax(raw_cmd)}")
                
            execute_command(raw_cmd)

if __name__ == "__main__":
    repl()
