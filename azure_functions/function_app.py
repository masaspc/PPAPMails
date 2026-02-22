"""Azure Functions アプリケーションエントリポイント

各Blueprint（process_email, cleanup_timer, health_check）を統合する。
"""

import azure.functions as func

from azure_functions.process_email import bp as process_email_bp
from azure_functions.cleanup_timer import bp as cleanup_timer_bp
from azure_functions.health_check import bp as health_check_bp

app = func.FunctionApp()

app.register_functions(process_email_bp)
app.register_functions(cleanup_timer_bp)
app.register_functions(health_check_bp)
