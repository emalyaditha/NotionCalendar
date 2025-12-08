import logging
import os
from datetime import datetime

# Remove existing error log file if it exists
ERROR_LOG_FILE = "error.log"

def setup_logging():
    if os.path.exists(ERROR_LOG_FILE):
        try:
            os.remove(ERROR_LOG_FILE)
        except:
            pass

    # Set up clean and readable logging
    class CleanFormatter(logging.Formatter):
        """Custom formatter for clean terminal output"""
        
        # Define color codes for different log levels
        COLORS = {
            'DEBUG': '\033[36m',    # Cyan
            'INFO': '\033[32m',     # Green
            'WARNING': '\033[33m',  # Yellow
            'ERROR': '\033[31m',    # Red
            'CRITICAL': '\033[35m', # Magenta
            'RESET': '\033[0m'      # Reset
        }
        
        def format(self, record):
            # Get timestamp
            timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
            
            # For ERROR and CRITICAL levels, write to error log file only
            if record.levelno >= logging.ERROR:
                error_msg = f"[{timestamp}] {record.levelname} | {record.getMessage()}\n"
                if record.exc_info:
                    error_msg += f"{self.formatException(record.exc_info)}\n"
                
                # Write to error log file
                try:
                    with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(error_msg)
                except:
                    pass  # If we can't write to file, continue anyway
                
                # Return empty string to prevent output to terminal
                return ""
            
            # Format for terminal output (only show INFO and WARNING in terminal)
            level_color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
            level_name = f"{level_color}{record.levelname:>8}{self.COLORS['RESET']}"
            formatted_message = f"[{timestamp}] {level_name} | {record.getMessage()}"
            return formatted_message

    # Configure logging with clean formatter
    logging.basicConfig(level=logging.INFO, handlers=[logging.FileHandler("sync.log")])
    logger = logging.getLogger("notion_sync")
    
    # Create console handler with clean formatter
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(CleanFormatter())
    logger.addHandler(console_handler)
    
    # Filter out ERROR and CRITICAL logs from console
    class ConsoleFilter(logging.Filter):
        def filter(self, record):
            # Only allow INFO and WARNING levels to console
            return record.levelno < logging.ERROR
    
    console_handler.addFilter(ConsoleFilter())
    
    return logger

logger = setup_logging()
