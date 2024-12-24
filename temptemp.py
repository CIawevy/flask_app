import re
# 方向词和标记词列表
direction_words = [
    "upward", "downward", "leftward", "rightward",
    "upper-left", "upper-right", "lower-left", "lower-right",
    "around", "uniformly"
]
# 编译正则表达式，用于匹配操作词、方向词和程度词
operation_words = ["Move", "Shift", "Slide", "Drag", "Rotate", "Spin", "Turn", "Swivel",
                   "Enlarge", "Expand", "zoom", "amplify", "Shrink", "Contract"]
degree_words = ["lightly", "slightly", "gently", "mildly", "moderately",
                "markedly", "appreciably", "heavily", "intensely", "significantly", "strongly"]
operation_mapping = {
    "Move": "Move", "Slide": "Move", "Shift": "Move", "Drag": "Move",
    "Rotate": "Rotate", "Spin": "Rotate", "Turn": "Rotate", "Swivel": "Rotate",
    "Enlarge": "Enlarge", "Expand": "Enlarge", "zoom": "Enlarge", "amplify": "Enlarge",
    "Shrink": "Shrink", "Contract": "Shrink"
}
# 创建方向词映射
direction_mapping = {
    "upward": "up", "downward": "down", "leftward": "left", "rightward": "right",
    "upper-left": "up-left", "upper-right": "up-right", "lower-left": "down-left", "lower-right": "down-right",
    "uniformly": "",
    'around the':"",
}
# 汇总所有需要去除的词
all_removal_words =  degree_words
removal_pattern = re.compile(r'\b(?:' + '|'.join(map(re.escape, all_removal_words)) + r')\b', re.IGNORECASE)
def shorten_prompt(prompt, obj_name=None):
    """
    简化 prompt 中的内容，去除对象名称和方向词等冗余内容，优化显示。
    """
    # Step 1: 特别处理 "around the"
    prompt = re.sub(r'\baround\s+the\b', '', prompt, flags=re.IGNORECASE)

    # Step 2: 移除 "the obj_name" 如果 obj_name 被提供
    if obj_name:
        prompt = re.sub(rf'\bthe\s+{re.escape(obj_name)}\b', '', prompt, flags=re.IGNORECASE)

    # Step 3: 移除其他指定的程度词
    prompt = removal_pattern.sub('', prompt)

    # Step 4: 替换操作词为统一形式
    for operation, unified_operation in operation_mapping.items():
        prompt = re.sub(r'\b' + re.escape(operation) + r'\b', unified_operation, prompt, flags=re.IGNORECASE)

    # Step 5: 替换方向词为统一形式
    for direction, unified_direction in direction_mapping.items():
        prompt = re.sub(r'\b' + re.escape(direction) + r'\b', unified_direction, prompt, flags=re.IGNORECASE)

    # Step 6: 清理多余空格
    prompt = re.sub(r'\s+', ' ', prompt).strip()

    return prompt


print(shorten_prompt('Turn the Leaning Tower around the y-axis counterclockwise lightly','Leaning Tower'))