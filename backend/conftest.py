import pathlib
import sys

# 保证 backend/ 在 sys.path，使 case_library / deepseek / report 等顶层模块可被测试导入
sys.path.insert(0, str(pathlib.Path(__file__).parent.resolve()))
