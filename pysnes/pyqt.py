# https://www.youtube.com/watch?v=-6nWreN4Z-c
import sys
import ctypes

import numpy as np
from OpenGL.GL import *

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QMouseEvent, QWheelEvent, QKeyEvent, QSurfaceFormat
from PyQt6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QApplication, QMainWindow, QHBoxLayout, QLabel, QWidget


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("My App")
        self.setFixedSize(800, 600)

        widget = QWidget()
        layout = QHBoxLayout()
        box1 = QLabel("left")
        box2 = OpenGLCanvas()
        box3 = QLabel("right")
        layout.addWidget(box1)
        layout.addWidget(box2)
        layout.addWidget(box3)
        widget.setLayout(layout)
        self.setCentralWidget(widget)

        timer = QTimer(self)
        timer.setInterval(20)   # period, in milliseconds
        timer.timeout.connect(box2.update)
        timer.start()


class OpenGLCanvas(QOpenGLWidget):
    def initializeGL(self) -> None:
        """Called once to set up the OpenGL rendering context before resize or paint are ever called"""
        vertices = np.array([
            -0.75, -0.75, 1, 0, 0,
            0.75, -0.75, 0, 1, 0,
            0.0, 0.75, 0, 0, 1,
        ], dtype=np.float32)

        self.VAO = glGenVertexArrays(1)
        glBindVertexArray(self.VAO)
        self.VBO = QOpenGLBuffer()
        self.VBO.create()
        self.VBO.bind()
        self.VBO.allocate(vertices, vertices.nbytes)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 5 * vertices.itemsize, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 5 * vertices.itemsize, ctypes.c_void_p(2 * vertices.itemsize))
        glEnableVertexAttribArray(1)

        glClearColor(0.5, 0.0, 0.25, 1.0)

        vertex_src = """
            #version 330 core
            layout(location = 0) in vec2 position;
            layout(location = 1) in vec3 color;
            out vec3 fragColor;
            void main() {
                gl_Position = vec4(position, 0.0, 1.0);
                fragColor = color;
            }
        """

        fragment_src = """
            #version 330 core
            in vec3 fragColor;
            out vec4 outColor;
            void main() {
                outColor = vec4(fragColor, 1.0);
            }
        """

        self.shader = QOpenGLShaderProgram(self)
        self.shader.addCacheableShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, vertex_src)
        self.shader.addCacheableShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, fragment_src)
        self.shader.link()
        self.shader.bind()

    def resizeGL(self, w: int, h: int) -> None:
        """Called once when the window is created and whenever the window is resized to set up the OpenGL viewport and projection"""
        return super().resizeGL(w, h)

    def paintGL(self) -> None:
        """Called when the widget is updated in order to render the scene"""
        glClear(GL_COLOR_BUFFER_BIT)
        self.shader.bind()
        glBindVertexArray(self.VAO)
        glDrawArrays(GL_TRIANGLES, 0, 3)


if __name__ == "__main__":
    format = QSurfaceFormat.defaultFormat()
    format.setMajorVersion(3)
    format.setMinorVersion(3)
    format.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QSurfaceFormat.setDefaultFormat(format)

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
    app = QApplication(sys.argv)
    w = Window()
    w.show()
    sys.exit(app.exec())
