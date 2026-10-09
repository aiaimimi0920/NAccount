"""仅公开固定命令/错误类别；不序列化子进程输出、参数或异常原文。"""
import re
from stack import StackError


class DeploymentCommandError(StackError):
    def __init__(self, operation, reason):
        # 这里的两个字段均由本模块生成，不接受外部文本作为公开诊断。
        if operation not in {'COMMAND', 'WRANGLER_DEPLOY', 'WRANGLER_SECRET'}:
            operation = 'COMMAND'
        if not re.fullmatch(r'(?:EXIT_NONZERO|NETWORK|SPAWN_FAILED|CF_[1-9][0-9]{3,5})', reason):
            reason = 'EXIT_NONZERO'
        self.code = operation + '_' + reason
        super().__init__(self.code)


def command_operation(command):
    if len(command) >= 3 and str(command[1]).replace('\\', '/').endswith('/wrangler/bin/wrangler.js'):
        if command[2] == 'deploy':
            return 'WRANGLER_DEPLOY'
        if command[2:4] == ['secret', 'bulk']:
            return 'WRANGLER_SECRET'
    return 'COMMAND'


def command_failure(command, stdout, stderr, *, secret_input=False):
    operation = command_operation(command)
    # secret bulk 的输出可能回显 stdin；不检查、更不输出该内容。
    if secret_input:
        return DeploymentCommandError(operation, 'EXIT_NONZERO')
    text = (stderr[-65536:] + stdout[-65536:]).decode('utf-8', errors='replace')
    codes = set(re.findall(r'\[code: ([1-9][0-9]{3,5})\]', text))
    if len(codes) == 1:
        return DeploymentCommandError(operation, 'CF_' + next(iter(codes)))
    if re.search(r'\b(?:ECONNRESET|ETIMEDOUT|ENOTFOUND|EAI_AGAIN|fetch failed)\b', text):
        return DeploymentCommandError(operation, 'NETWORK')
    return DeploymentCommandError(operation, 'EXIT_NONZERO')


def result_error(stage_code, error):
    if isinstance(error, DeploymentCommandError):
        value = stage_code.removesuffix('_FAILED') + '_' + error.code
        if re.fullmatch(r'[A-Z][A-Z0-9_]{1,79}', value):
            return value
    return stage_code
