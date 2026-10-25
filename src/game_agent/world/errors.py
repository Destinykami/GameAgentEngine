"""保存错误契约，不依赖存储或世界运行。"""


class SaveError(RuntimeError):
    def __init__(self, stage: str, npc_name: str | None, cause: Exception) -> None:
        self.stage = stage
        self.npc_name = npc_name
        self.detail = str(cause)
        subject = f'NPC {npc_name}' if npc_name is not None else '世界'
        super().__init__(f'{subject} 保存失败 ({stage}): {cause}')
