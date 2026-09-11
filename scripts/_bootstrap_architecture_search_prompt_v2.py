from pathlib import Path

path = Path(__file__).resolve().parents[1] / "src/api.py"
text = path.read_text(encoding="utf-8")
old = '''- M8336 是 DVIT 中断输入指定功能有效，不是 ZRN/DSZR 完成标志。M8029 必须与对应指令关联；需要确认机械停止时使用驱动器定位完成输入。\n'''
new = '''- D8345是回原点爬行速度，不是 DRVI/DRVA 的最高速度参数；不得因为删除候选方案范例而丢失这条型号事实。\n- M8336 是 DVIT 中断输入指定功能有效，不是 ZRN/DSZR 完成标志。M8029 必须与对应指令关联；需要确认机械停止时使用驱动器定位完成输入。\n'''
if text.count(old) != 1:
    raise RuntimeError(f"motion-fact anchor count={text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
print("applied: preserve D8345 motion fact in analysis knowledge")
