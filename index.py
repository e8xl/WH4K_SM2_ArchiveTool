import configparser
import getpass
import os
import re
import shutil
import sys
import threading
import time
import warnings

from PyQt6.QtCore import QTimer, Qt, QUrl
from PyQt6.QtGui import QIcon, QDesktopServices
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QLineEdit, QTextEdit, QLabel, \
    QMessageBox, QComboBox, QDialog, QDialogButtonBox

warnings.filterwarnings("ignore", category=DeprecationWarning)
# 配置文件路径
CONFIG_FILE = "config.ini"


def is_valid_windows_path(path: str) -> bool:
    """ 检测路径是否为有效的Windows路径格式 """
    windows_path_regex = r'^[a-zA-Z]:[\\/](?:[^\\/:*?"<>|\r\n]+[\\/]?)*$'
    return bool(re.match(windows_path_regex, path))


def resource_path(relative_path):
    """获取资源文件的绝对路径，适用于开发和 PyInstaller 打包后的环境"""
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def is_system_directory(path: str) -> bool:
    """检查路径是否为系统关键目录"""
    system_dirs = [
        os.environ.get('SYSTEMROOT', r'C:\Windows'),
        os.environ.get('PROGRAMFILES', r'C:\Program Files'),
        os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)'),
        os.environ.get('USERPROFILE', r'C:\Users'),
        r'C:\\',
    ]
    # 规范化路径
    norm_path = os.path.normpath(path).lower()
    for sys_dir in system_dirs:
        norm_sys_dir = os.path.normpath(sys_dir).lower()
        if norm_path == norm_sys_dir or norm_path.startswith(norm_sys_dir + os.sep):
            return True
    return False


def is_valid_game_save_path(path: str) -> bool:
    """检查路径是否为有效的游戏存档路径"""
    # 这里可以根据实际的游戏存档路径结构进行检查
    expected_subdirs = ['storage', 'steam', 'user']
    norm_path = os.path.normpath(path).lower()
    path_parts = norm_path.split(os.sep)
    return all(subdir in path_parts for subdir in expected_subdirs)


class FileSyncApp(QMainWindow):
    def __init__(self, icon_path=None):
        super().__init__()

        self.setWindowTitle("为了帝皇！")
        self.setGeometry(300, 300, 600, 400)

        # 禁止窗口缩放
        self.setFixedSize(self.width(), self.height())

        # 将窗口显示在屏幕中央
        self.center()

        if icon_path:
            icon_full_path = resource_path(icon_path)
            self.setWindowIcon(QIcon(icon_full_path))

        # 初始化配置
        self.config = configparser.ConfigParser()
        self.first_run = True
        self.load_config()

        # 界面布局
        self.layout = QVBoxLayout()

        # 标题
        self.title_label = QLabel("存档同步器", self)
        self.layout.addWidget(self.title_label)

        # A目录 (用户输入)
        self.a_label = QLabel("修改存档路径 (A目录):", self)
        self.layout.addWidget(self.a_label)
        self.a_input = QLineEdit(self)
        self.layout.addWidget(self.a_input)

        # B目录 (游戏存档路径)
        self.b_label = QLabel("游戏存档路径 (B目录):", self)
        self.layout.addWidget(self.b_label)

        # 获取当前用户默认路径
        username = getpass.getuser()
        default_b_path = rf"C:\Users\{username}\AppData\Local\Saber\Space Marine 2\storage\steam\user\[SteamID]\Main\config"
        self.b_input = QLineEdit(default_b_path, self)
        self.layout.addWidget(self.b_input)

        self.select_label = QLabel('填入路径或选择你想要修改的存档', self)
        self.layout.addWidget(self.select_label)

        # 创建下拉框
        self.save_combo = QComboBox(self)
        self.save_combo.addItems(['', '选择全满级存档', '选择全皮肤存档[等级随机]'])
        self.save_combo.currentIndexChanged.connect(self.on_save_combo_changed)
        self.layout.addWidget(self.save_combo)

        # 日志输出框
        self.log_output = QTextEdit(self)
        self.log_output.setReadOnly(True)
        self.layout.addWidget(self.log_output)

        # 日志默认文本
        self.log_output.append("欢迎使用战锤40K: 星际战士2 存档同步器")
        self.log_output.append("请设置修改存档目录和游戏存档目录，并点击开始同步")
        self.log_output.append("Author:e1GhtXL_")



        # 开始/停止按钮
        self.start_button = QPushButton("开始同步", self)
        self.start_button.clicked.connect(self.toggle_sync)
        self.layout.addWidget(self.start_button)

        # 快捷寻找游戏存档路径 按钮
        self.find_save_button = QPushButton("快捷寻找游戏存档路径", self)
        self.find_save_button.clicked.connect(self.find_game_save_path)
        self.layout.addWidget(self.find_save_button)

        # 关于按钮
        self.about_button = QPushButton("关于 (About)", self)
        self.about_button.clicked.connect(self.show_about)
        self.layout.addWidget(self.about_button)

        # 定时器用于更新日志
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_log)

        # 初始化线程和状态
        self.sync_thread = None
        self.is_syncing = False
        self.log_messages = []

        # 创建主窗口
        widget = QWidget()
        widget.setLayout(self.layout)

        self.setCentralWidget(widget)

        # 检查是否第一次运行
        if self.first_run:
            self.show_warning()
        else:
            self.load_previous_paths()

    def on_save_combo_changed(self, index):
        if index == 1:  # '选择全满级存档'
            base_path = resource_path('')
            path = os.path.join(base_path, 'Save', 'quanmanji_cundang', 'Main', 'config')
            self.a_input.setText(path)
        elif index == 2:  # '选择全皮肤存档[等级随机]'
            base_path = resource_path('')
            path = os.path.join(base_path, 'Save', 'QuanPifu[LevelRandom]', 'Main', 'config')
            self.a_input.setText(path)
        else:
            # 清空 A 目录输入框
            self.a_input.clear()

    def center(self):
        """将窗口移动到屏幕中央"""
        screen = self.screen().availableGeometry().center()  # 使用 QScreen 获取屏幕几何
        frame_geo = self.frameGeometry()
        frame_geo.moveCenter(screen)
        self.move(frame_geo.topLeft())

    def show_warning(self):
        """ 显示第一次运行时的警告信息，并询问用户是否对帝皇忠诚 """
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setWindowTitle("帝皇法令")
        msg_box.setText("公民，这是您首次运行此程序。\n\n"
                        "您是否宣誓对人类之神皇绝对忠诚？\n\n"
                        "请确保您已正确设置存档目录。\n"
                        "请注意备份，游戏存档目录将被直接覆盖。\n\n"
                        "您是否愿意以帝皇之名继续？")

        btn_loyal = msg_box.addButton("为了帝皇！", QMessageBox.ButtonRole.AcceptRole)
        btn_heresy = msg_box.addButton("异端！", QMessageBox.ButtonRole.RejectRole)
        msg_box.exec()

        if msg_box.clickedButton() == btn_loyal:
            # 用户选择 "为了帝皇！"，进入主程序
            self.log_output.append("用户宣誓了对帝皇的忠诚，进入主程序。")
            self.config['Settings']['Loyalty'] = 'False'  # 修改为 False 表示同意条款
            with open(CONFIG_FILE, 'w') as configfile:
                self.config.write(configfile)
        else:
            # 用户选择 "异端！"，显示提示框并退出程序
            self.log_output.append("用户被判定为异端，程序将关闭。")
            self.config['Settings']['Loyalty'] = 'True'  # 保持 True，确保下次启动继续提示
            with open(CONFIG_FILE, 'w') as configfile:
                self.config.write(configfile)

            # 显示自定义的退出对话框
            QMessageBox.information(self, "异端审判", "您已拒绝对帝皇的忠诚，程序将关闭。", QMessageBox.StandardButton.Ok)
            self.close()  # 关闭主窗口，退出程序
            sys.exit()  # 确保退出应用程序

    def toggle_sync(self):
        self.log_output.clear()

        if not self.is_syncing:
            # 获取用户输入的A目录和B目录
            source_dir = self.a_input.text().strip()
            target_dir = self.b_input.text().strip()

            # 检查A目录和B目录输入框是否为空
            if not source_dir or not target_dir:
                QMessageBox.warning(self, "错误", "A目录和B目录不能为空，请输入有效的目录路径。")
                return

            # 检查A目录和B目录是否为有效的Windows路径格式
            if not is_valid_windows_path(source_dir) or not is_valid_windows_path(target_dir):
                QMessageBox.warning(self, "错误", "A目录或B目录不是有效的Windows路径格式，请输入正确的路径。")
                return

            # 检查A目录是否为空或无效
            if not os.path.exists(source_dir) or not os.listdir(source_dir):
                QMessageBox.warning(self, "错误", "A目录为空或不存在，请检查后再试。")
                return

            # 检查B目录是否存在且不为空
            if not os.path.exists(target_dir) or not os.listdir(target_dir):
                QMessageBox.warning(self, "错误", "B目录为空或不存在，请检查后再试。")
                return

            # 检查B目录是否为系统关键目录
            if is_system_directory(target_dir):
                QMessageBox.critical(self, "严重错误", "B目录为系统关键目录，不能进行同步操作！")
                return

            # 检查B目录是否为有效的游戏存档路径
            if not is_valid_game_save_path(target_dir):
                reply = QMessageBox.question(
                    self,
                    '警告',
                    'B目录可能不是有效的游戏存档路径，是否继续？',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    QMessageBox.information(self, "操作取消", "同步已取消。")
                    return

            # 保存A和B路径到配置文件
            self.save_paths(source_dir, target_dir)

            # 启动同步
            self.start_sync(source_dir, target_dir)
            self.start_button.setText("停止同步")
        else:
            # 停止同步
            self.stop_sync()
            self.start_button.setText("开始同步")
            self.log_output.append("同步已结束")

    def start_sync(self, source_dir, target_dir):
        try:
            self.is_syncing = True
            # 为了避免无错误提示的闪退，捕获线程中的所有异常
            self.sync_thread = threading.Thread(target=self.sync_folders_periodically, args=(source_dir, target_dir))
            self.sync_thread.start()
            self.timer.start(1000)  # 每秒更新日志
        except Exception as e:
            self.log_output.append(f"同步启动时发生错误: {str(e)}")

    def stop_sync(self):
        self.is_syncing = False
        if self.sync_thread:
            self.sync_thread.join()
        self.timer.stop()

    def sync_folders_periodically(self, source_dir, target_dir):
        while self.is_syncing:
            try:
                self.sync_folders(source_dir, target_dir)
                self.log_messages.append(f"同步检查完成: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            except Exception as e:
                self.log_messages.append(f"同步时发生错误: {str(e)}")
            time.sleep(1)

    def sync_folders(self, source_dir, target_dir):
        try:
            source_files = set()
            target_files = set()

            # 遍历A目录
            for root, dirs, files in os.walk(source_dir):
                for file in files:
                    source_files.add(os.path.relpath(os.path.join(root, file), source_dir))

            # 遍历B目录
            for root, dirs, files in os.walk(target_dir):
                for file in files:
                    target_files.add(os.path.relpath(os.path.join(root, file), target_dir))

            # 比较A和B目录，判断是否有不同
            if source_files != target_files:
                self.log_messages.append("检测到文件差异，开始同步...")
                shutil.rmtree(target_dir)
                self.copy_files(source_dir, target_dir)
            else:
                self.log_messages.append("文件没有差异，无需同步。")
        except Exception as e:
            self.log_messages.append(f"文件同步时发生错误: {str(e)}")

    def copy_files(self, source_dir, target_dir):
        try:
            # 复制文件
            for root, dirs, files in os.walk(source_dir):
                relative_path = os.path.relpath(root, source_dir)
                target_path = os.path.join(target_dir, relative_path)

                if not os.path.exists(target_path):
                    os.makedirs(target_path)

                for file in files:
                    source_file = os.path.join(root, file)
                    target_file = os.path.join(target_path, file)
                    shutil.copy2(source_file, target_file)
                    self.log_messages.append(f"复制: {source_file} -> {target_file}")
        except Exception as e:
            self.log_messages.append(f"复制文件时发生错误: {str(e)}")

    def update_log(self):
        # 更新日志
        while self.log_messages:
            self.log_output.append(self.log_messages.pop(0))

    def load_config(self):
        """ 加载配置文件 """
        try:
            if os.path.exists(CONFIG_FILE):
                self.config.read(CONFIG_FILE)
                if self.config.has_section('Settings'):
                    self.first_run = self.config.getboolean('Settings', 'Loyalty')
            else:
                # 第一次运行，创建配置文件
                self.create_config()
        except Exception as e:
            self.log_output.append(f"加载配置文件时发生错误: {str(e)}")

    def create_config(self):
        """ 创建新的配置文件 """
        try:
            self.config['Settings'] = {'Loyalty': 'True'}  # 第一次运行设为 True，表示尚未同意条款
            with open(CONFIG_FILE, 'w') as configfile:
                self.config.write(configfile)
            # 设置文件为隐藏文件
            # ctypes.windll.kernel32.SetFileAttributesW(CONFIG_FILE, 0x02)  # 0x02 表示隐藏文件
        except Exception as e:
            self.log_output.append(f"创建配置文件时发生错误: {str(e)}")

    def save_paths(self, a_path, b_path):
        """ 保存A和B路径到配置文件 """
        try:
            self.config['Paths'] = {'a_path': a_path, 'b_path': b_path}
            self.config['Settings']['first_run'] = 'False'
            with open(CONFIG_FILE, 'w') as configfile:
                self.config.write(configfile)
        except Exception as e:
            self.log_output.append(f"保存路径时发生错误: {str(e)}")

    def load_previous_paths(self):
        """ 加载上次保存的A和B路径 """
        try:
            if self.config.has_section('Paths'):
                self.a_input.setText(self.config.get('Paths', 'a_path'))
                self.b_input.setText(self.config.get('Paths', 'b_path'))
        except Exception as e:
            self.log_output.append(f"加载路径时发生错误: {str(e)}")

    def find_game_save_path(self):
        """快速寻找游戏存档路径"""
        local_appdata = os.environ.get('LOCALAPPDATA')
        if not local_appdata:
            QMessageBox.warning(self, "错误", "无法获取 %LOCALAPPDATA% 路径。")
            return

        user_path = os.path.join(local_appdata, 'Saber', 'Space Marine 2', 'storage', 'steam', 'user')
        if not os.path.exists(user_path):
            QMessageBox.warning(self, "错误", "未找到游戏存档目录，请确保游戏已安装并运行过。")
            return

        # 列出 user_path 下的目录
        dirs = [d for d in os.listdir(user_path) if os.path.isdir(os.path.join(user_path, d))]

        # 匹配以 "7656" 开头且总共17位数字的目录
        steamid_pattern = re.compile(r'^7656\d{13}$')
        steamid_dirs = [d for d in dirs if steamid_pattern.match(d)]

        if not steamid_dirs:
            QMessageBox.information(self, "提示", "无法为你找到游戏存档目录，请自行查找教程填写。")
            return

        elif len(steamid_dirs) == 1:
            steamid = steamid_dirs[0]
            save_path = os.path.join(user_path, steamid, 'Main', 'config')
            self.b_input.setText(save_path)
            QMessageBox.information(self, "找到游戏存档路径", f"已为你找到游戏存档路径:\n{save_path}")
        else:
            # 多个 SteamID 目录，提供选择
            self.select_steamid_dialog(steamid_dirs, user_path)

    def select_steamid_dialog(self, steamid_dirs, user_path):
        dialog = QDialog(self)
        dialog.setWindowTitle("选择你的SteamID")
        layout = QVBoxLayout()

        instruction_label = QLabel("检测到多个SteamID文件夹，请选择你的SteamID：")
        layout.addWidget(instruction_label)

        # 添加“查询自己的SteamID”按钮
        find_steamid_button = QPushButton("查询自己的SteamID")
        find_steamid_button.clicked.connect(self.open_steamid_help)
        layout.addWidget(find_steamid_button)

        # 添加下拉框供用户选择 SteamID
        steamid_combo = QComboBox()
        steamid_combo.addItems(steamid_dirs)
        layout.addWidget(steamid_combo)

        # 添加确定和取消按钮
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        dialog.setLayout(layout)

        if dialog.exec():
            selected_steamid = steamid_combo.currentText()
            save_path = os.path.join(user_path, selected_steamid, 'Main', 'config')
            self.b_input.setText(save_path)
            QMessageBox.information(self, "找到游戏存档路径", f"已为你选择的SteamID找到游戏存档路径:\n{save_path}")
        else:
            QMessageBox.information(self, "操作取消", "未选择SteamID，操作已取消。")

    def open_steamid_help(self):
        QDesktopServices.openUrl(QUrl("https://www.bilibili.com/read/cv18150980/"))

    def show_about(self):
        """ 显示关于对话框 """
        about_dialog = QMessageBox(self)
        about_dialog.setWindowTitle("About")
        about_dialog.setText(
            'Author: e1GhtXL_<br>'
            '<a href="https://github.com/e8xl">Github</a><br>'
            '<a href="https://ifdian.net/a/888xl">赞助</a>'
        )
        about_dialog.setTextFormat(Qt.TextFormat.RichText)  # 支持超链接
        about_dialog.exec()


def main(icon_path=None):
    # 创建应用程序
    app = QApplication([])
    window = FileSyncApp(icon_path=icon_path)
    window.show()
    app.exec()


if __name__ == "__main__":
    main(icon_path="icon.ico")  # 传入自定义图标路径
