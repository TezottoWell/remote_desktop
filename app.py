import sys
import socket
import threading
import pyautogui
import cv2
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                             QMessageBox, QDesktopWidget, QFrame)
from PyQt5.QtGui import QImage, QPixmap, QIcon, QFont
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import pyperclip
import mss
import zlib

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception as e:
        print(f"Erro ao obter IP local: {e}")
        return '127.0.0.1'

class ServerThread(QThread):
    def __init__(self, host, port):
        super().__init__()
        self.host = host
        self.port = port
        self.server_socket = None
        self.client_socket = None
        self.running = False
    
    def run(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(1)
            print(f"Servidor aguardando conexão em {self.host}:{self.port}")
            
            self.client_socket, address = self.server_socket.accept()
            print(f"Conectado com: {address}")
            
            self.running = True
            
            while self.running:
                try:

                    with mss.mss() as sct:
                        monitor = sct.monitors[0]
                        screenshot = np.array(sct.grab(monitor))
                        

                    _, buffer = cv2.imencode('.jpg', screenshot, [cv2.IMWRITE_JPEG_QUALITY, 50])
                    compressed_img = zlib.compress(buffer)
                    
                    self.client_socket.sendall(len(compressed_img).to_bytes(4, byteorder='big'))
                    self.client_socket.sendall(compressed_img)
                    
                    # Processar comandos recebidos
                    self.process_commands()
                    
                except Exception as e:
                    print(f"Erro durante transmissão: {e}")
                    break
        
        except Exception as e:
            print(f"Erro no servidor: {e}")
        
        finally:
            if self.server_socket:
                self.server_socket.close()
    
    def process_commands(self):

        try:
            command = self.client_socket.recv(1024).decode('utf-8')
            if command.startswith('MOUSE_MOVE'):
                _, x, y = command.split(',')
                pyautogui.moveTo(int(x), int(y))
            elif command.startswith('MOUSE_CLICK'):
                _, button = command.split(',')
                pyautogui.click(button=button)
            elif command.startswith('KEY_PRESS'):
                _, key = command.split(',')
                pyautogui.press(key)
        except:
            pass
    
    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()

class ClientThread(QThread):
    image_update = pyqtSignal(QImage)
    
    def __init__(self, host, port):
        super().__init__()
        self.host = host
        self.port = port
        self.client_socket = None
        self.running = False
    
    def run(self):
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((self.host, self.port))
            self.running = True
            
            while self.running:

                img_size_bytes = self.client_socket.recv(4)
                if not img_size_bytes:
                    break
                
                img_size = int.from_bytes(img_size_bytes, byteorder='big')
                

                compressed_img = b''
                while len(compressed_img) < img_size:
                    chunk = self.client_socket.recv(min(img_size - len(compressed_img), 4096))
                    if not chunk:
                        break
                    compressed_img += chunk
                

                decompressed_img = zlib.decompress(compressed_img)
                nparr = np.frombuffer(decompressed_img, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                # Converter para formato QImage
                rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_image.shape
                bytes_per_line = ch * w
                qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
                
                self.image_update.emit(qt_image)
        
        except Exception as e:
            print(f"Erro no cliente: {e}")
        
        finally:
            if self.client_socket:
                self.client_socket.close()
    
    def send_mouse_move(self, x, y):
        if self.client_socket:
            self.client_socket.send(f'MOUSE_MOVE,{x},{y}'.encode('utf-8'))
    
    def send_mouse_click(self, button='left'):
        if self.client_socket:
            self.client_socket.send(f'MOUSE_CLICK,{button}'.encode('utf-8'))
    
    def send_key_press(self, key):
        if self.client_socket:
            self.client_socket.send(f'KEY_PRESS,{key}'.encode('utf-8'))

class FullScreenRemoteView(QMainWindow):
    close_signal = pyqtSignal()
    mouse_move_signal = pyqtSignal(int, int)
    mouse_click_signal = pyqtSignal(str)
    key_press_signal = pyqtSignal(str)

    def __init__(self, client_thread):
        super().__init__()
        self.client_thread = client_thread
        self.initUI()
        self.setup_event_handlers()

    def initUI(self):

        self.setWindowTitle('Tela Remota')
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.showFullScreen()

        # Layout principal
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout()

        # Label para exibir tela remota
        self.screen_label = QLabel('Tela Remota')
        self.screen_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.screen_label)

        central_widget.setLayout(layout)

    def setup_event_handlers(self):
        # Eventos de mouse
        self.screen_label.mouseMoveEvent = self.mouseMoveEvent
        self.screen_label.mousePressEvent = self.mousePressEvent
        self.screen_label.mouseReleaseEvent = self.mouseReleaseEvent

        # Evento de teclado
        self.keyPressEvent = self.handle_key_press

    def update_screen(self, image):
        pixmap = QPixmap.fromImage(image)
        scaled_pixmap = pixmap.scaled(self.screen_label.size(), 
                                      Qt.KeepAspectRatio, 
                                      Qt.SmoothTransformation)
        self.screen_label.setPixmap(scaled_pixmap)

    def mouseMoveEvent(self, event):

        label_width = self.screen_label.width()
        label_height = self.screen_label.height()
        
        x = int((event.x() / label_width) * 1920)  
        y = int((event.y() / label_height) * 1080)
        
        self.mouse_move_signal.emit(x, y)

    def mousePressEvent(self, event):
        button = 'left' if event.button() == 1 else 'right'
        self.mouse_click_signal.emit(button)

    def mouseReleaseEvent(self, event):
        pass  # TODO: lógica de soltar botão

    def handle_key_press(self, event):

        key = event.text()
        if key:
            self.key_press_signal.emit(key)

    def keyReleaseEvent(self, event):
        # Permite sair da tela cheia com ESC
        if event.key() == Qt.Key_Escape:
            self.close()
            self.close_signal.emit()

class RemoteAccessApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.setupStyleSheet()
        
        # Inicializar threads
        self.server_thread = None
        self.client_thread = None
        
        self.start_server()
    
    def setupStyleSheet(self):

        self.setStyleSheet("""
            QMainWindow {
                background-color: #2C3E50;
                color: #ECF0F1;
            }
            
            QLabel {
                color: #ECF0F1;
                font-size: 14px;
            }
            
            QLineEdit {
                padding: 8px;
                border: 2px solid #34495E;
                border-radius: 5px;
                background-color: #34495E;
                color: #ECF0F1;
                font-size: 14px;
            }
            
            QPushButton {
                background-color: #3498DB;
                color: white;
                border: none;
                padding: 10px 15px;
                border-radius: 5px;
                font-weight: bold;
                font-size: 14px;
            }
            
            QPushButton:hover {
                background-color: #2980B9;
            }
            
            QPushButton:pressed {
                background-color: #21618C;
            }
            
            #statusLabel {
                color: #2ECC71;
                font-weight: bold;
            }
        """)
    
    def initUI(self):
        self.setWindowTitle('Controle Remoto Avançado')
        self.setGeometry(100, 100, 1000, 700)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout()
        
        # Área de conexão com estilo de card
        connection_frame = QFrame()
        connection_frame.setStyleSheet("""
            QFrame {
                background-color: #34495E;
                border-radius: 10px;
                padding: 15px;
            }
        """)
        connection_layout = QHBoxLayout()
        

        connection_title = QLabel('Configurações de Conexão')
        connection_title.setFont(QFont('Arial', 16, QFont.Bold))
        main_layout.addWidget(connection_title)
        

        host_label = QLabel('Endereço IP:')
        port_label = QLabel('Porta:')
        
        local_ip = get_local_ip()
        self.host_input = QLineEdit(local_ip)
        self.host_input.setPlaceholderText('Digite o IP do host')
        
        self.port_input = QLineEdit('5000')
        self.port_input.setPlaceholderText('Porta de conexão')
        

        self.copy_ip_btn = QPushButton('Copiar IP')
        self.server_btn = QPushButton('Parar Servidor')
        self.client_btn = QPushButton('Conectar')
        
        connection_layout.addWidget(host_label)
        connection_layout.addWidget(self.host_input)
        connection_layout.addWidget(port_label)
        connection_layout.addWidget(self.port_input)
        connection_layout.addWidget(self.copy_ip_btn)
        connection_layout.addWidget(self.server_btn)
        connection_layout.addWidget(self.client_btn)
        
        connection_frame.setLayout(connection_layout)
        main_layout.addWidget(connection_frame)
        

        self.status_label = QLabel('Status: Pronto para Conexão')
        self.status_label.setObjectName('statusLabel')
        main_layout.addWidget(self.status_label)
        

        self.screen_label = QLabel('Tela Remota')
        self.screen_label.setAlignment(Qt.AlignCenter)
        self.screen_label.setStyleSheet("""
            QLabel {
                background-color: #283747;
                border: 2px dashed #34495E;
                border-radius: 10px;
                min-height: 400px;
            }
        """)
        main_layout.addWidget(self.screen_label)
        
        central_widget.setLayout(main_layout)
        

        self.server_btn.clicked.connect(self.start_server)
        self.client_btn.clicked.connect(self.connect_client)
        self.copy_ip_btn.clicked.connect(self.copy_ip)
        

        self.center()
    
    def center(self):
        # Centraliza a janela na tela
        frame_geometry = self.frameGeometry()
        screen_center = QDesktopWidget().availableGeometry().center()
        frame_geometry.moveCenter(screen_center)
        self.move(frame_geometry.topLeft())
    
    def copy_ip(self):
        """
        Copia o IP para área de transferência
        """
        ip = self.host_input.text()
        pyperclip.copy(ip)
        QMessageBox.information(self, 'IP Copiado', f'IP {ip} copiado para área de transferência')
    
    def start_server(self):
        host = self.host_input.text() or '0.0.0.0'
        port = int(self.port_input.text() or 5000)
        
        try:

            if self.server_thread and self.server_thread.isRunning():
                self.server_thread.stop()
            
            self.server_thread = ServerThread(host, port)
            self.server_thread.start()
            
            # Altera o texto e o estilo do botão
            self.server_btn.setText('Parar Servidor')
            self.server_btn.setStyleSheet("""
                QPushButton {
                    background-color: #E74C3C;
                    color: white;
                    border: none;
                    padding: 10px 15px;
                    border-radius: 5px;
                    font-weight: bold;
                    font-size: 14px;
                }
                
                QPushButton:hover {
                    background-color: #C0392B;
                }
                
                QPushButton:pressed {
                    background-color: #B03A2E;
                }
            """)
            

            self.server_btn.clicked.disconnect()
            self.server_btn.clicked.connect(self.stop_server)
            
            self.status_label.setText(f'Status: Servidor iniciado em {host}:{port}')
            QMessageBox.information(self, 'Servidor', f'Servidor iniciado em {host}:{port}')
        except Exception as e:
            QMessageBox.critical(self, 'Erro', f'Falha ao iniciar servidor: {e}')
    
    def stop_server(self):
        if self.server_thread and self.server_thread.isRunning():
            self.server_thread.stop()
            

            self.server_btn.setText('Iniciar Servidor')
            self.server_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3498DB;
                    color: white;
                    border: none;
                    padding: 10px 15px;
                    border-radius: 5px;
                    font-weight: bold;
                    font-size: 14px;
                }
                
                QPushButton:hover {
                    background-color: #2980B9;
                }
                
                QPushButton:pressed {
                    background-color: #21618C;
                }
            """)
            

            self.server_btn.clicked.disconnect()
            self.server_btn.clicked.connect(self.start_server)
            
            self.status_label.setText('Status: Servidor Parado')
            QMessageBox.information(self, 'Servidor', 'Servidor parado com sucesso')
    
    def connect_client(self):
        host = self.host_input.text()
        port = int(self.port_input.text() or 5000)
        
        try:
            self.client_thread = ClientThread(host, port)
            

            self.fullscreen_view = FullScreenRemoteView(self.client_thread)
            

            self.client_thread.image_update.connect(self.fullscreen_view.update_screen)
            

            self.fullscreen_view.mouse_move_signal.connect(self.client_thread.send_mouse_move)
            self.fullscreen_view.mouse_click_signal.connect(self.client_thread.send_mouse_click)
            self.fullscreen_view.key_press_signal.connect(self.client_thread.send_key_press)
            self.fullscreen_view.close_signal.connect(self.on_fullscreen_closed)
            

            self.client_thread.start()
            self.fullscreen_view.show()
            

            self.hide()
            
            self.status_label.setText(f'Status: Conectado a {host}:{port}')
        except Exception as e:
            QMessageBox.critical(self, 'Erro', f'Falha ao conectar: {e}')
    
    def on_fullscreen_closed(self):
        self.show()
        if self.client_thread:
            self.client_thread.running = False
            self.client_thread.quit()

def main():
    app = QApplication(sys.argv)
    remote_app = RemoteAccessApp()
    remote_app.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()