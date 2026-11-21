# 辞书的单词查询

运行 `python3 lexicon_v1.py case.json 松` 可单查“松”。Python 调用为 `lookup_word(source, word_id)`。结果给出词号、原文字串、从零数的词内重音位置（轻读词为 null），以及逐字本韵、本调。查不到词或组成它的字条时，命令退出非零，标准错误报告原因，标准输出为空。
