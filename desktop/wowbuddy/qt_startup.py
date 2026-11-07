"""分阶段启动的Qt计时器宿主；业务次序来自startup_stages。"""
from PySide6.QtCore import QObject, QTimer
from .startup_stages import StartupCallbacks, StartupStages


class QtStartup(QObject):
    def __init__(self, app, splash, loader, *, construct_main, record,
                 after_main=lambda window:None, auto_start=False, after_authorization=lambda:None):
        super().__init__(app)
        self.app=app
        self.splash=splash
        self.delays=[]
        self.timer=QTimer(self)
        def authorized():
            splash.accept_local_authorization()
            after_authorization()
        callbacks=StartupCallbacks(
            show_splash=splash.show,process_events=app.processEvents,record=record,
            progress=splash.set_progress,start_timer=self.timer.start,stop_timer=self.timer.stop,
            schedule=self.schedule,construct_main=construct_main,close_splash=splash.close,
            delete_splash_later=splash.deleteLater,show_main=lambda window:window.show(),
            auto_start=lambda window:window.auto_start_once(),after_main=after_main,
            local_authorized=authorized,quit_application=self.cancel)
        self.stages=StartupStages(loader,callbacks,auto_start=auto_start)
        self.timer.timeout.connect(self.stages.tick)
        splash.cancelled.connect(self.stages.cancel_from_splash)
        self.app.aboutToQuit.connect(self.close)

    def schedule(self, milliseconds, callback):
        timer=QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(callback)
        self.delays.append(timer)
        timer.start(milliseconds)

    def start(self):
        self.stages.show_splash()
        if self.stages.phase=='awaiting_local_authorization':
            self.stages.accept_local_authorization()

    def cancel(self):
        self.close()
        self.app.quit()
        # show/processEvents可能发生在app.exec之前；此时quit本身不结束后续exec。
        QTimer.singleShot(0,self.app,self.app.quit)

    def close(self):
        self.timer.stop()
        for timer in self.delays:
            timer.stop()
