"""插件热更直接安装回调；不修改手动安装面板选项或最近目录。"""
from .addon_actions import validate_destination
from .addon_install import plan_install
from .addon_update import ReinstallResult


class AddonReinstaller:
    def __init__(self, settings, files, package_provider, *, random_u32=None):
        self.settings, self.files = settings, files
        self.package_provider, self.random_u32 = package_provider, random_u32

    def __call__(self, path):
        try:
            error, _ = validate_destination(path, self.files)
            if error:
                return ReinstallResult(False, error=error)
            plan = plan_install(self.package_provider(), path,
                existing_entries=self.files.entries(path), existing_directories=self.files.directories(path),
                random_u32=self.random_u32, absolute_path=self.files.absolute_path)
            result = self.files.write_install(plan)
            if not result.ok:
                return ReinstallResult(False, error=result.error)
            if result.pending_record is not None:
                self.settings.qsettings.setValue(result.pending_record.key, result.pending_record.value)
            cleanup = self.files.plan_cleanup(path, plan.addon_name, names=result.pending_cleanup)
            self.files.execute_cleanup(cleanup, selected_path=path)
            return ReinstallResult(True, plan.addon_name)
        except (OSError, ValueError) as error:
            return ReinstallResult(False, error=str(error))
