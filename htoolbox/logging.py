import logging
import os
import re
from pathlib import Path

from rich.logging import RichHandler
from rich.text import Text

RST = "\x1b[0m"
BRI = "\x1b[1m"
UND = "\x1b[4m"

BLACK = "\x1b[30m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
BLUE = "\x1b[34m"
PURPLE = "\x1b[35m"
CYAN = "\x1b[36m"
WHITE = "\x1b[37m"

BBLACK = "\x1b[1;30m"
BRED = "\x1b[1;31m"
BGREEN = "\x1b[1;32m"
BYELLOW = "\x1b[1;33m"
BBLUE = "\x1b[1;34m"
BPURPLE = "\x1b[1;35m"
BCYAN = "\x1b[1;36m"
BWHITE = "\x1b[1;37m"

UBLACK = "\x1b[4;30m"
URED = "\x1b[4;31m"
UGREEN = "\x1b[4;32m"
UYELLOW = "\x1b[4;33m"
UBLUE = "\x1b[4;34m"
UPURPLE = "\x1b[4;35m"
UCYAN = "\x1b[4;36m"
UWHITE = "\x1b[4;37m"


def print_ft(s: str = None, c: str = None, leading=10, *args, **kwargs):
    if s is None or s == "":
        s = ""
    else:
        s = f" {s} "
    print(filling_terminal(s, c=c, leading=leading), *args, **kwargs)


def filling_terminal(s: str = None, c: str = None, leading=10) -> str:
    if s is None:
        s = ""
    if c is None:
        c = "-"
    try:
        columns = os.get_terminal_size().columns
    except OSError:
        columns = 256
    trailing = columns - len(s) - leading
    if trailing < 0:
        trailing = 0
    s = f"{BRI}" + c * leading + s + c * trailing + f"{RST}"
    return s


PRINT_LEVEL_NUM = 60
logging.addLevelName(PRINT_LEVEL_NUM, "PRINT")
LOGGER = None


class HTLogger(logging.Logger):
    def print(self, message, *args, **kwargs):
        if self.isEnabledFor(PRINT_LEVEL_NUM):
            self._log(PRINT_LEVEL_NUM, message, args, **kwargs)

    def info_ft(self, s: str, c: str = None, leading=10, *args, **kwargs):
        if self.isEnabledFor(logging.INFO):
            if s is None or s == "":
                s = ""
            else:
                s = f" {s} "
            self._log(
                logging.INFO, filling_terminal(s, c=c, leading=leading), args, **kwargs
            )

    def print_ft(self, s: str, c: str = None, leading=10, *args, **kwargs):
        if self.isEnabledFor(PRINT_LEVEL_NUM):
            if s is None or s == "":
                s = ""
            else:
                s = f" {s} "
            self._log(
                PRINT_LEVEL_NUM,
                filling_terminal(s, c=c, leading=leading),
                args,
                **kwargs,
            )


logging.setLoggerClass(HTLogger)


def get_logger(name, level=logging.INFO, mode: str = "w", path=None) -> HTLogger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    # if level == logging.DEBUG:
    if level == logging.DEBUG:
        logger.addHandler(RichHandler(level=logging.DEBUG))
    if path is not None:
        logger.addHandler(logging.FileHandler(path, mode))
    return logger


class AnsiAwareRichHandler(RichHandler):
    def render_message(self, record, message):
        if "\033" in message:
            return Text.from_ansi(message)

        return super().render_message(record, message)


class StripAnsiFormatter(logging.Formatter):
    _ansi_re = re.compile(r"\x1b\[[0-9;]*m")

    def format(self, record):
        message = super().format(record)
        return self._ansi_re.sub("", message)


def init_global_logger(
    name: str = "HToolbox",
    # For console logging
    console_level: int = logging.INFO,
    show_time: bool = True,
    show_level: bool = True,
    show_path: bool = False,
    enable_rich: bool = True,
    # For file logging
    file_level: int = logging.INFO,
    mode: str = "w",
    path: Path = None,
    file_time_format: str = "%Y/%m/%d %H:%M:%S",
    file_format: str = "%(asctime)s %(levelname)s %(message)s",
    file_shadow_ansi: bool = True,
):
    """
    Docstring for init_global_logger

    :param file_shadow_ansi: If path provided, and this is True, we will
    create a shadow log file without ANSI stripped.
    """
    global LOGGER
    logger = logging.getLogger(name)
    lowest_level = min(console_level, file_level)
    logger.setLevel(lowest_level)

    # Setup console handler
    if enable_rich:
        console_handler = AnsiAwareRichHandler(
            level=console_level,
            show_time=show_time,
            show_level=show_level,
            show_path=show_path,
            log_time_format="%Y/%m/%d %H:%M:%S",
        )
    else:
        console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    logger.addHandler(console_handler)

    # Setup file handler
    if path is not None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, mode)
        file_handler.setFormatter(
            StripAnsiFormatter(fmt=file_format, datefmt=file_time_format)
        )
        file_handler.setLevel(file_level)
        logger.addHandler(file_handler)
        if file_shadow_ansi:
            shadow_path = path.with_suffix(".ansi" + path.suffix)
            print(shadow_path)
            shadow_handler = logging.FileHandler(shadow_path, mode)
            shadow_handler.setFormatter(
                logging.Formatter(fmt=file_format, datefmt=file_time_format)
            )
            shadow_handler.setLevel(file_level)
            logger.addHandler(shadow_handler)
    LOGGER = logger
    return LOGGER


def get_global_logger() -> HTLogger:
    global LOGGER
    if LOGGER is None:
        init_global_logger()
    return LOGGER
