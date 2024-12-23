import os
import cv2
import json
import argparse
import threading
import base64
import random
from fontTools.subset import subset
from numba.tests.inlining_usecases import inner
from tqdm import tqdm
from flask_app import Flask, render_template, request, redirect, url_for, send_file, session
import os.path as osp
import secrets
from flask_session import Session  # 新增
from flask_app import g  # 新增
import  time
from io import BytesIO
import os
from tqdm import  tqdm
global_data = {}
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
app.config.update(
    SESSION_TYPE='filesystem',
    SESSION_PERMANENT=True,
    SESSION_FILE_DIR='./flask_session/',
    SESSION_USE_SIGNER=True,
    SECRET_KEY='your_secret_key_here',
)
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
Session(app)
@app.template_filter('b64encode')
def b64encode_filter(image_bytes):
    """
    Custom Jinja filter to base64 encode image bytes.
    :param image_bytes: BytesIO object or image data
    :return: Base64 encoded string
    """
    return base64.b64encode(image_bytes.getvalue()).decode('utf-8')
@app.template_filter('random_color')
def random_color_filter(index):
    colors = [
        '#FF5733',  # 鲜红橙色
        # '#33FF57',  # 鲜绿色（过亮，难以辨识）
        '#3357FF',  # 中等蓝色
        # '#F1C40F',  # 金黄色
        '#9B59B6',  # 深紫色
        '#1ABC9C',  # 青绿色
        '#E74C3C',  # 鲜红色
        '#34495E',  # 深蓝灰色
        '#2ECC71',  # 草绿色
        '#3498DB',  # 浅蓝色
        '#8E44AD',  # 紫罗兰色
        '#27AE60',  # 深绿色
        '#E67E22',  # 橙色
        '#E84393',  # 粉红色
    ]
    return colors[index % len(colors)]

def get_user_info(username):
    """动态加载用户信息"""
    user_dir = osp.join(os.environ.get("DATASET_DIR"), 'users', username)  # 用户文件夹路径
    user_info_path = osp.join(user_dir, 'user_info.json')  # 用户数据文件路径

    # 如果文件夹不存在，则初始化
    if not os.path.exists(user_dir):
        os.makedirs(user_dir, exist_ok=True)
        user_info = {
            'selected_subset': None,
            'contributions': {},
            'start_progress': 0,
        }
        print(f'initializing user info for {username}')
        save_user_info(username, user_info)  # 保存初始用户信息
    else:
        with open(user_info_path, 'r') as f:
            user_info = json.load(f)


    return user_info


def save_user_info(username, user_info):
    """保存用户信息到用户文件夹"""
    user_dir = osp.join(os.environ.get("DATASET_DIR"), 'users', username)  # 用户文件夹路径
    user_info_path = osp.join(user_dir, 'user_info.json')  # 用户数据文件路径

    # 保存用户信息到文件
    with open(user_info_path, 'w') as f:
        json.dump(user_info, f, indent=4)
from PIL import Image, ImageOps
from PIL import Image, ImageEnhance
def crop_to_content(image):
    """
    自动裁剪图片的白边。
    :param image: PIL.Image 对象
    :return: 裁剪后的 PIL.Image 对象
    """
    # 根据图像模式设置背景颜色
    if image.mode == "RGB":
        bg_color = (255, 255, 255)
    elif image.mode == "L":
        bg_color = 255
    elif image.mode == "1":
        bg_color = True
    else:
        raise ValueError(f"Unsupported image mode: {image.mode}")

    # 去掉明显的白边
    bg = Image.new(image.mode, image.size, bg_color)
    diff = ImageOps.invert(ImageOps.autocontrast(image)).convert("L")
    bbox = diff.getbbox()
    return image.crop(bbox) if bbox else image

def resize_to_match(image, target_size):
    """
    将图片调整为目标大小。
    :param image: PIL.Image 对象
    :param target_size: 目标尺寸 (宽, 高)
    :return: 调整后的 PIL.Image 对象
    """
    return image.resize(target_size, Image.Resampling.LANCZOS)
def image_to_bytes(image):
    """
    将 PIL 图像转换为字节流。
    :param image: PIL.Image 对象
    :return: 字节流
    """
    img_byte_arr = BytesIO()
    image.save(img_byte_arr, format='PNG')  # 保存为 PNG 格式
    img_byte_arr.seek(0)  # 返回到流的开始位置
    return img_byte_arr
def initialize_ori_data_stat(data, ori_data_stat_path, num_dict):
    """
    初始化或加载 ori_data_stat 的逻辑。

    :param data: 原始子集数据
    :param ori_data_stat_path: 保存 ori_data_stat 的文件路径
    :param num_dict: 每张图片掩码数量的字典
    :return: 初始化或加载的 ori_data_stat 字典
    """
    # 计算总 mask 数量，仅包含有效的 instances
    total_mask_results = sum(
        sum(level_masks.values()) for level_masks in num_dict.values()
    )

    # 加载状态数据
    if os.path.exists(ori_data_stat_path):
        # 如果文件存在，加载状态数据
        ori_data_stat = load_json_data(ori_data_stat_path)
    else:
        # 如果文件不存在，初始化状态数据
        ori_data_stat = {
            da_n: {
                'status': 'unprocessed',
                'processed_masks': [],  # 用于记录已处理的 mask
                'level': None,  # 当前未选择 level
            } for da_n in data.keys()
        }
        ori_data_stat['total_mask_results'] = total_mask_results  # 总 mask 数量
        ori_data_stat['processed_mask_results'] = 0  # 已处理 mask 数量
        # 保存初始化的状态数据
        save_json_data(ori_data_stat, ori_data_stat_path)

    return ori_data_stat
def load_or_initialize_global_data(root_dir):
    """加载或初始化全局变量"""
    global global_data

    # 过滤只保留以 Subset_ 开头的子集目录
    subset_dirs = sorted(
        [d for d in os.listdir(root_dir) if d.startswith("Subset_") and os.path.isdir(os.path.join(root_dir, d))],
        key=lambda x: int(x.split("_")[1])  # 提取数字部分进行排序
    )

    # 初始化进度条
    with tqdm(total=len(subset_dirs), desc="Initializing datasets...") as pbar:
        for subset_dir in subset_dirs:
            subset_id = subset_dir.split("_")[1]
            subset_path = os.path.join(root_dir, subset_dir)

            # 如果 global_data 中没有此子集，加载或初始化它
            if subset_id not in global_data:
                global_data[subset_id] = initialize_subset_data(subset_path, subset_id)

            # 每完成一个子集，更新进度条
            pbar.update(1)


def save_global_data_periodically(root_dir, interval=300):
    """定期保存全局变量到磁盘"""
    global global_data
    global_data_path = os.path.join(root_dir, 'global_data.json')

    def save_loop():
        while True:
            with open(global_data_path, 'w') as f:
                json.dump(global_data, f, indent=4)
            time.sleep(interval)

    threading.Thread(target=save_loop, daemon=True).start()

# 加载或创建掩码数据的函数
def load_json_data(json_path):
    with open(json_path, 'r') as f:
        data = json.load(f)
    return data
# 加载数据的通用函数：如果文件不存在则创建空字典并保存
def load_or_create_json(path):
    if os.path.exists(path):
        return load_json_data(path)
    else:
        # 文件不存在时，初始化为空字典
        save_json_data({}, path)
        return {}
# 保存筛选后的数据
def save_json_data(data, json_path):
    with open(json_path, 'w') as f:
        json.dump(data, f, indent=4)


# # 重新定义 undo_stack 的最大长度
# MAX_UNDO_STACK_SIZE = 100000000
def load_or_create_undo_stack(file_path):
    """加载或创建撤销栈"""
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                undo_stack = json.load(f)
                # 如果不是列表，返回空列表
                if isinstance(undo_stack, list):
                    return undo_stack
                else:
                    print(f"Warning: Undo stack at {file_path} is not a list. Initializing empty stack.")
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading undo stack from {file_path}: {e}. Initializing empty stack.")
    # 如果文件不存在或读取失败，创建空列表并保存
    save_undo_stack([], file_path)
    return []
def initialize_subset_data(subset_path, subset_id):
    """
    初始化或加载子集的数据。

    :param subset_path: 子集目录路径
    :param subset_id: 子集的唯一标识
    :return: 初始化的子集数据结构
    """
    # 动态加载或创建数据文件
    data_path = os.path.join(subset_path, f"packed_data_full_tag_{subset_id}.json")
    ori_data_stat_path = os.path.join(subset_path, "ssm_ram_stat.json")
    undo_stack_path = os.path.join(subset_path, "ssm_ram_undo_stack.json")
    new_data_path = os.path.join(subset_path, "ssm_ram_edit_data.json")

    # 加载或创建 JSON 数据
    data = load_or_create_json(data_path)
    new_data = load_or_create_json(new_data_path)

    # 动态生成 num_dict
    num_dict = get_num_dict(data)

    # 初始化或加载 ori_data_stat
    ori_data_stat = initialize_ori_data_stat(data, ori_data_stat_path, num_dict)

    # 加载或创建撤销栈
    undo_stack = load_or_create_undo_stack(undo_stack_path)

    # 返回完整的子集数据结构
    return {
        "data": data,
        "ori_data_stat": ori_data_stat,
        "undo_stack": undo_stack,
        "new_data": new_data,
        "num_dict": num_dict,
        "paths": {
            "data": data_path,
            "ori_data_stat": ori_data_stat_path,
            "undo_stack": undo_stack_path,
            "new_data": new_data_path,
        }
    }
def get_num_dict(data):
    """根据子集数据生成 num_dict"""
    return {
        da_n: {
            inst['level']: len(inst['mask_path']) for inst in da.get('instances', [])
        } for da_n, da in data.items()
    }
# 定义保存和加载 undo_stack 的方法
def save_undo_stack(undo_stack, undo_stack_path):
    # if len(undo_stack) > MAX_UNDO_STACK_SIZE:
    #     undo_stack = undo_stack[-MAX_UNDO_STACK_SIZE:]  # 保留最近的10次操作
    with open(undo_stack_path, 'w') as f:
        json.dump(undo_stack, f, indent=4)

def load_undo_stack(undo_stack_path):
    if os.path.exists(undo_stack_path):
        with open(undo_stack_path, 'r') as f:
            undo_stack = json.load(f)
            return undo_stack if isinstance(undo_stack, list) else []
    return []








# 用户登录路由
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        user_info = get_user_info(username)  # 动态加载用户信息
        return redirect(url_for('select_subset', username=username))  # 跳转到选择子集页面
    return render_template('login.html')

def update_and_collect_user_contributions(progress_stat):
    """
    更新所有用户的贡献并返回聚合的贡献数据。
    :param progress_stat: 当前的进度状态
    :return: contributions_data 聚合后的贡献数据
    """
    contributions_data = {}  # 用于存储所有用户的贡献
    user_base_dir = osp.join(os.environ.get("DATASET_DIR"), 'users')  # 用户文件夹根目录

    if not os.path.exists(user_base_dir):
        print("No user data found!")
        return contributions_data

    for user_folder in os.listdir(user_base_dir):
        user_dir = osp.join(user_base_dir, user_folder)
        if not os.path.isdir(user_dir):
            continue  # 跳过非文件夹项

        user_info_path = osp.join(user_dir, 'user_info.json')
        if not os.path.exists(user_info_path):
            continue

        with open(user_info_path, 'r') as f:
            user_info = json.load(f)

        # 如果用户选择了子集，则更新贡献
        if user_info.get('selected_subset') is not None:
            subset_id = user_info['selected_subset']
            cur_progress = progress_stat[subset_id]['progress']
            start_progress = user_info.get('start_progress', 0)
            contribution = cur_progress - start_progress

            if contribution > 0:
                user_info['contributions'][subset_id] = (
                    user_info['contributions'].get(subset_id, 0) + contribution
                )
                user_info['start_progress'] = cur_progress

            # 保存更新后的用户信息
            with open(user_info_path, 'w') as f:
                json.dump(user_info, f, indent=4)

        # 聚合当前用户的贡献数据
        for subset_id, contribution in user_info.get('contributions', {}).items():
            if subset_id not in contributions_data:
                contributions_data[subset_id] = {}
            contributions_data[subset_id][user_folder] = contribution

    return contributions_data
# 选择子集页面
# 选择子集页面
# 修改 /select_subset/<username> 路由
@app.route('/select_subset/<username>', methods=['GET', 'POST'])
def select_subset(username):
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'logout':
            return redirect(url_for('logout', username=username))  # 重定向到登录页面
        progress_stat = get_progress_stat()  # 动态加载 progress_stat
        user_info = get_user_info(username)
        subset_id = request.form.get('subset_id')
        subset_id = str(subset_id)  # 确保 subset_id 是字符串
        if progress_stat[subset_id]['user'] != 'unselected':
            return redirect(url_for('select_subset', username=username))
        else:
            user_info['selected_subset'] = subset_id  # 更新用户选择的子集
            progress_stat[subset_id]['user'] = username  # 更新子集的用户信息
            user_info['start_progress'] = progress_stat[subset_id]['progress']  # 记录当前进度
            save_user_info(username, user_info)  # 保存用户信息
            save_progress_stat(progress_stat)  # 保存 progress_stat 到文件
            return redirect(url_for('inner_init', username=username, subset_id=subset_id))  # 选择子集后跳转到主页面

    progress_stat = get_progress_stat()  # 动态加载 progress_stat
    user_info = get_user_info(username)
    # 先赞停当前用户选择的子集并收集贡献，避免重复统计
    #每个子集同时只能被一个人选择或者不选择，每个人当前选择也只能有一个子集
    if user_info.get('selected_subset') is not None:
        subset_id = user_info['selected_subset']
        cur_progress = progress_stat[subset_id]['progress']
        start_progress = user_info.get('start_progress', 0)
        contribution = cur_progress - start_progress

        if contribution > 0:
            if subset_id not in user_info['contributions']:
                user_info['contributions'][subset_id] = contribution
            else:
                user_info['contributions'][subset_id] += contribution

        # 更新 start_progress 防止重复计算
        user_info['start_progress'] = cur_progress

    # 清除当前用户的子集选择
    user_info['selected_subset'] = None
    save_user_info(username, user_info)  # 保存用户信息
    # 更新并收集所有用户的贡献数据
    contributions_data = update_and_collect_user_contributions(progress_stat)
    print(contributions_data)
    #先收集 再暂时unselected
    for subset_id, data in progress_stat.items():
        if data['user'] == username:
            progress_stat[subset_id]['user'] = 'unselected'  # 重置为未选中状态
    save_progress_stat(progress_stat)  # 保存 progress_stat 到文件

    # 构造子集的显示信息
    subsets = []
    for subset_id, data in progress_stat.items():
        disable = data['user'] != 'unselected' and username != data['user'] or data['progress'] >= 100
        subsets.append({
            'subset_id': subset_id,
            'progress': data['progress'],
            'status': data['status'],
            'user': data['user'],
            'is_disabled': disable
        })

    # 从 contributions_data 构建用户索引信息 分配可视化颜色
    user_indices = {}
    for subset_id, user_contributions in contributions_data.items():
        for user in user_contributions.keys():
            if user not in user_indices:
                user_indices[user] = len(user_indices)

    return render_template(
        'select_subset.html',
        progress_stat=subsets,
        username=username,
        contributions_data=contributions_data,
        user_indices=user_indices  # 传递用户索引
    )

# 退出登录
@app.route('/logout/<username>', methods=['GET'])
def logout(username):
    progress_stat = get_progress_stat()  # 动态加载进度状态
    user_info = get_user_info(username)  # 动态加载当前用户信息

    # 更新 progress_stat，释放子集
    for subset_id, data in progress_stat.items():
        if data['user'] == username:
            data['user'] = 'unselected'  # 重置为未选中状态

    # 保存 progress_stat
    save_progress_stat(progress_stat)

    # 统计贡献并更新用户信息
    if user_info.get('selected_subset') is not None:
        subset_id = user_info['selected_subset']
        cur_progress = progress_stat[subset_id]['progress']
        start_progress = user_info.get('start_progress', 0)
        contribution = cur_progress - start_progress

        if contribution > 0:
            if subset_id not in user_info['contributions']:
                user_info['contributions'][subset_id] = contribution
            else:
                user_info['contributions'][subset_id] += contribution

        # 更新 start_progress 防止重复计算
        user_info['start_progress'] = cur_progress

    # 清除当前用户的子集选择
    user_info['selected_subset'] = None

    # 保存更新后的用户信息
    print(f'save user info for {username}')
    save_user_info(username, user_info)

    return redirect(url_for('login'))  # 返回登录页面



def apply_random_color_to_mask(mask_img, color_index=0):
    """
    根据提供的颜色索引为掩码区域着色。
    """
    def random_color_filter(index):
        colors = [
            '#FF5733',  # 鲜红橙色
            '#3357FF',  # 中等蓝色
            '#9B59B6',  # 深紫色
            '#1ABC9C',  # 青绿色
            '#E74C3C',  # 鲜红色
            '#34495E',  # 深蓝灰色
            '#2ECC71',  # 草绿色
            '#3498DB',  # 浅蓝色
            '#8E44AD',  # 紫罗兰色
            '#27AE60',  # 深绿色
            '#E67E22',  # 橙色
            '#E84393',  # 粉红色
        ]
        return colors[index % len(colors)]

    def hex_to_rgba(hex_color, alpha=150):
        hex_color = hex_color.lstrip('#')
        return (
            int(hex_color[0:2], 16),
            int(hex_color[2:4], 16),
            int(hex_color[4:6], 16),
            alpha
        )

    # 获取掩码数据
    mask_data = mask_img.getdata()
    selected_color = hex_to_rgba(random_color_filter(color_index), alpha=150)

    new_mask_data = [
        selected_color if value > 0 else (0, 0, 0, 0)  # 非零区域使用颜色
        for value in mask_data
    ]
    mask_img_colored = Image.new("RGBA", mask_img.size)
    mask_img_colored.putdata(new_mask_data)
    return mask_img_colored

def combine_with_transparent_background(original_img, mask_img_colored, alpha=0.5):
    """
    将原图透明化后，与着色的掩码进行叠加。
    """
    # 降低原图亮度/透明度
    transparent_bg = Image.new("RGBA", original_img.size, (255, 255, 255, int(255 * (1 - alpha))))
    original_transparent = Image.alpha_composite(transparent_bg, original_img)

    # 将掩码叠加到透明化的原图上
    combined_img = Image.alpha_composite(original_transparent, mask_img_colored)
    return combined_img


def filter_instance(data, da_n, mask_id, level):
    src_img_path = data[da_n]['src_img_path']
    instances = data[da_n]['instances'][level - 1]
    mask_path = instances['mask_path'][int(mask_id)]

    # 打开原图和掩码图
    ori_img = Image.open(src_img_path).convert("RGBA")
    mask_img = Image.open(mask_path).convert("L")

    # 调整掩码尺寸以匹配原图
    if mask_img.size != ori_img.size:
        mask_img = mask_img.resize(ori_img.size, Image.NEAREST)


    # 生成合成图像：裁剪掩码区域，其他部分填充为白色
    white_background = Image.new("RGBA", ori_img.size, (255, 255, 255, 255))  # 白色背景
    crop_img = Image.composite(ori_img, white_background, mask_img)  # 保留掩码区域

    # 返回数据
    return {
        'ori_img': image_to_bytes(ori_img),          # 原图
        # 'ori_mask': image_to_bytes( mask_img),  # 着色掩码图
        'crop_img': image_to_bytes(crop_img),       # 裁剪后的合成图像
        'obj_label': instances['obj_label'][int(mask_id)],     # 目标标签
    }
# 动态加载图片的路由
@app.route('/file/<path:filename>')
def serve_image(filename):
    file_path = filename
    if not file_path.startswith('/'):  # 如果路径不是以斜杠开头，手动添加斜杠
        file_path = '/' + file_path

    print(f"Trying to load file: {file_path}")
    if os.path.exists(file_path):
        return send_file(file_path)
    else:
        return "File not found", 404

@app.route('/inner_select/<username>/<subset_id>', methods=['GET', 'POST'])
def inner_select(username, subset_id):
    global global_data

    # 获取子集数据
    subset_data = global_data[subset_id]
    data = subset_data['data']
    ori_data_stat = subset_data['ori_data_stat']

    # 遍历子集中的图片
    for da_n, da in data.items():
        # 跳过没有有效 instances 的图片
        if 'instances' not in da or ori_data_stat[da_n]['status'] == 'completed':
            continue

        # 判断是否进入 level 选择
        if ori_data_stat[da_n]['status'] == 'unprocessed':
            return redirect(url_for('select_level', username=username, subset_id=subset_id, da_n=da_n))

        # 判断是否已选择 level
        if ori_data_stat[da_n]['status'] == 'selected':
            level = ori_data_stat[da_n]['level']
            # 继续处理 mask
            mask_paths = da['instances'][level - 1]['mask_path']
            processed_masks = [int(mask) for mask in ori_data_stat[da_n].get('processed_masks', [])]

            for mask_id, mask_path in enumerate(mask_paths):
                if mask_id not in processed_masks:
                    # 返回当前未处理的 mask
                    return redirect(url_for('filter', username=username, subset_id=subset_id, da_n=da_n, mask_id=mask_id, level=level))

    # 如果所有图片均已完成，更新全局进度
    progress_stat = get_progress_stat()
    progress_stat[subset_id]['status'] = 'completed'
    save_progress_stat(progress_stat)

    return redirect(url_for('select_subset', username=username))

@app.route('/inner_init/<username>/<subset_id>', methods=['GET', 'POST'])
def inner_init(username, subset_id):
    global global_data
    dataset_dir = os.environ.get("DATASET_DIR")
    directory = os.path.join(dataset_dir, f'Subset_{subset_id}')

    if subset_id not in global_data:
        # 加载或初始化子集数据
        json_path = os.path.join(directory, f"packed_data_full_tag_{subset_id}.json")
        new_data_path = os.path.join(directory, f'ssm_ram_edit_data.json')
        undo_stack_path = os.path.join(directory, 'ssm_ram_undo_stack.json')
        ori_data_stat_path = os.path.join(directory, 'ssm_ram_stat.json')

        data = load_json_data(json_path)
        num_dict = {
            da_n: {
                inst['level']: len(inst['mask_path']) for inst in da['instances']
            } if 'instances' in da else {}
            for da_n, da in data.items()
        }
        total_mask_results = sum(sum(level_masks.values()) for level_masks in num_dict.values())

        # 加载或初始化状态
        if os.path.exists(ori_data_stat_path):
            ori_data_stat = load_json_data(ori_data_stat_path)
        else:
            ori_data_stat = {
                da_n: {
                    'status': 'unprocessed',
                    'processed_masks': [],
                    'level': None,
                } for da_n in data.keys()
            }
            ori_data_stat['total_mask_results'] = total_mask_results
            ori_data_stat['processed_mask_results'] = 0
            save_json_data(ori_data_stat, ori_data_stat_path)

        # 加载 undo_stack 和 new_data
        undo_stack = load_undo_stack(undo_stack_path)
        new_data = load_or_create_json(new_data_path)

        # 存储到全局变量
        global_data[subset_id] = {
            'data': data,
            'num_dict': num_dict,
            'ori_data_stat': ori_data_stat,
            'undo_stack': undo_stack,
            'new_data': new_data,
            'paths': {
                'ori_data_stat': ori_data_stat_path,
                'undo_stack': undo_stack_path,
                'new_data': new_data_path,
            }
        }

    return redirect(url_for('inner_select', username=username, subset_id=subset_id))
@app.route('/')
def index():
    return redirect(url_for('login'))
    # 遍历数据中的图片


@app.route('/select_level/<username>/<subset_id>/<da_n>', methods=['GET', 'POST'])
def select_level(username, subset_id, da_n):
    global global_data

    # 获取子集数据
    subset_data = global_data[subset_id]
    data = subset_data['data']
    ori_data_stat = subset_data['ori_data_stat']
    undo_stack = subset_data['undo_stack']
    num_dict = subset_data['num_dict']
    new_data = subset_data['new_data']

    if request.method == 'POST':
        action = request.form.get('action')  # 获取用户的动作
        selected_level = request.form.get('level')  # 获取用户选择的分割级别

        # 处理不同的动作
        if action == 'skip_image':
            # 跳过整张图片
            total_edits_in_image = sum(num_dict[da_n].values())
            ori_data_stat[da_n]['status'] = 'completed'
            ori_data_stat['processed_mask_results'] += total_edits_in_image
            undo_stack.append(('skip_image', da_n, total_edits_in_image))

        elif action == 'undo':
            # 撤销上一步操作
            if undo_stack:
                last_action = undo_stack.pop()
                action_type, undo_da_n, *details = last_action

                if action_type == 'skip_image' or action_type == 'Next':
                    # 撤回跳过图片的操作
                    ori_data_stat[undo_da_n]['status'] = 'unprocessed' if action_type == 'skip_image' else 'selected'
                    ori_data_stat['processed_mask_results'] -= details[0]

                elif action_type == 'select_level':
                    # 撤回选择级别的操作
                    ori_data_stat[undo_da_n]['status'] = 'unprocessed'
                    ori_data_stat[undo_da_n]['level'] = None
                    # 返回 `select_level` 界面
                    return redirect(url_for('select_level', username=username, subset_id=subset_id, da_n=undo_da_n))
                elif action_type == 'keep':
                    # 撤回“保留”操作
                    new_data[undo_da_n]['instances']['mask_path'].pop()
                    ori_data_stat[undo_da_n]['processed_masks'].remove(details[0])
                    ori_data_stat['processed_mask_results'] -= 1
                    ori_data_stat[undo_da_n]['status'] = 'selected'

                elif action_type == 'skip':
                    # 撤回“跳过”操作
                    ori_data_stat[undo_da_n]['processed_masks'].remove(details[0])
                    ori_data_stat['processed_mask_results'] -= 1
                    ori_data_stat[undo_da_n]['status'] = 'selected'


        elif action == 'logout':
            # 登出用户并重定向到登录页面
            return redirect(url_for('logout', username=username))  # 重定向到登录页面


        elif action == 'go_to_main':

            # 在返回主页时先更新所有用户的贡献
            return redirect(url_for('select_subset',username=username))

        elif selected_level:
            # 用户选择了一个分割级别
            selected_level = int(selected_level)
            ori_data_stat[da_n]['status'] = 'selected'
            ori_data_stat[da_n]['level'] = selected_level
            undo_stack.append(('select_level', da_n, selected_level))

        # 保存状态
        save_json_data(ori_data_stat, subset_data['paths']['ori_data_stat'])
        save_undo_stack(undo_stack, subset_data['paths']['undo_stack'])

        # 重定向到内部处理逻辑页面
        return redirect(url_for('inner_select', username=username, subset_id=subset_id))

    # 准备渲染数据
    directory = subset_data['paths']['ori_data_stat'].rsplit('/', 1)[0]
    level_images = {
        level: osp.join(directory, f'masks_tag/level{level}/{da_n}/anotated_img.png')
        for level in num_dict[da_n].keys()
    }

    original_image_path = data[da_n]['src_img_path']
    level_images['Original'] = original_image_path  # 保留原图路径

    # 打开原图并获取大小
    original_image = Image.open(original_image_path)
    target_size = original_image.size  # 获取原图尺寸作为目标大小

    # 处理所有图像（裁剪并调整大小），包括 "Original" 图像
    processed_images = {}
    for level, img_path in level_images.items():
        img = Image.open(img_path)
        img = crop_to_content(img)  # 去掉白边
        img = resize_to_match(img, target_size)  # 调整为原图尺寸
        # 将处理后的图像转换为字节流
        processed_images[level] = image_to_bytes(img)

    # 计算进度百分比
    progress_stat = get_progress_stat()
    progress = "{:.2f}".format(
        (ori_data_stat['processed_mask_results'] / ori_data_stat['total_mask_results']) * 100
    )
    progress_stat[subset_id]['progress'] = float(progress)
    save_progress_stat(progress_stat)

    # 检查是否禁用撤回按钮
    disable_undo = len(undo_stack) == 0

    # 渲染模板
    return render_template(
        'level_selection_plus.html',
        da_n=da_n,
        subset_id=subset_id,
        username=username,
        level_images=processed_images,  # 传递处理后的图像字节流给模板
        progress=progress,
        undo_stack=undo_stack[-20:],  # 只传递后 N 条记录
        disable_undo=disable_undo
    )


@app.route('/filter/<username>/<subset_id>/<da_n>/<mask_id>/<level>', methods=['GET', 'POST'])
def filter(username, subset_id, da_n, mask_id, level):
    global global_data

    if request.method == 'POST':
        # 获取子集数据
        subset_data = global_data[subset_id]
        data = subset_data['data']
        ori_data_stat = subset_data['ori_data_stat']
        undo_stack = subset_data['undo_stack']
        new_data = subset_data['new_data']
        num_dict = subset_data['num_dict']
        level = int(level)
        decision = request.form['decision']

        if decision == 'keep':
            # 保留该 mask 结果到 new_data
            if da_n not in new_data:
                new_data[da_n] = {'instances': {'mask_path': []}}
            new_data[da_n]['instances']['mask_path'].append(
                data[da_n]['instances'][level - 1]['mask_path'][int(mask_id)]
            )

            # 更新处理状态
            ori_data_stat[da_n]['processed_masks'].append(mask_id)
            ori_data_stat['processed_mask_results'] += 1
            if len(ori_data_stat[da_n]['processed_masks']) == sum(subset_data['num_dict'][da_n].values()):
                ori_data_stat[da_n]['status'] = 'completed'
            undo_stack.append(('keep', da_n, mask_id))

        elif decision == 'skip':
            # 跳过当前 mask
            ori_data_stat[da_n]['processed_masks'].append(mask_id)
            ori_data_stat['processed_mask_results'] += 1
            if len(ori_data_stat[da_n]['processed_masks']) == sum(subset_data['num_dict'][da_n].values()):
                ori_data_stat[da_n]['status'] = 'completed'
            undo_stack.append(('skip', da_n, mask_id))

        elif decision == 'Next':
            # 跳过剩余所有
            print(f'decision: Next')
            total_edits_in_image = sum(num_dict[da_n].values())
            already_process_image = len(ori_data_stat[da_n]['processed_masks'])
            process_ins_num = total_edits_in_image - already_process_image
            ori_data_stat[da_n]['status'] = 'completed'
            ori_data_stat['processed_mask_results'] += process_ins_num
            undo_stack.append(('Next', da_n,  process_ins_num))

        elif decision == 'undo':
            if undo_stack:
                last_action = undo_stack.pop()
                action_type, undo_da_n, undo_mask_id = last_action

                if action_type == 'keep':
                    # 撤回“保留”操作
                    new_data[undo_da_n]['instances']['mask_path'].pop()
                    ori_data_stat[undo_da_n]['processed_masks'].remove(undo_mask_id)
                    ori_data_stat['processed_mask_results'] -= 1

                elif action_type == 'skip':
                    # 撤回“跳过”操作
                    ori_data_stat[undo_da_n]['processed_masks'].remove(undo_mask_id)
                    ori_data_stat['processed_mask_results'] -= 1

                # 恢复状态为“unprocessed”，如果撤销了所有处理
                if not ori_data_stat[undo_da_n]['processed_masks']:
                    ori_data_stat[undo_da_n]['status'] = 'selected'

        elif decision == 'undo_level_select':
            # 撤销当前 level 的所有处理
            processed_masks = ori_data_stat[da_n]['processed_masks']
            undo_count = len(processed_masks)
            ori_data_stat['processed_mask_results'] -= undo_count
            ori_data_stat[da_n]['processed_masks'] = []
            ori_data_stat[da_n]['status'] = 'unprocessed'
            ori_data_stat[da_n]['level'] = None

            # 清空撤销栈中相关记录
            undo_stack[:] = [
                action for action in undo_stack if action[1] != da_n
            ]

        # 保存更新后的状态
        save_json_data(new_data, subset_data['paths']['new_data'])
        save_json_data(ori_data_stat, subset_data['paths']['ori_data_stat'])
        save_undo_stack(undo_stack, subset_data['paths']['undo_stack'])

        return redirect(url_for('inner_select', username=username, subset_id=subset_id))

    # 获取子集数据
    subset_data = global_data[subset_id]
    data = subset_data['data']
    ori_data_stat = subset_data['ori_data_stat']
    undo_stack = subset_data['undo_stack']

    level = int(level)
    progress_stat = get_progress_stat()
    # 计算进度百分比
    progress = "{:.2f}".format(
        (ori_data_stat['processed_mask_results'] / ori_data_stat['total_mask_results']) * 100
    )
    progress_stat[subset_id]['progress'] = float(progress)
    save_progress_stat(progress_stat)

    # 获取 mask 实例信息
    instance_info = filter_instance(data, da_n, mask_id, level)

    # 动态更新按钮状态
    disable_skip_image = False  # 动态设置
    # 检查撤回栈顶部操作类型，只有类型为 keep 或 skip 时才启用撤销按钮
    disable_undo_last_action = not (undo_stack and undo_stack[-1][0] in ['keep', 'skip'])

    # 渲染模板，并传递所需数据
    return render_template(
        'mask_filter_plus.html',
        username=username,
        subset_id=subset_id,
        instance=instance_info,
        progress=progress,
        undo_stack=undo_stack[-20:],  # 只传递后 N 条记录
        disable_skip_image=disable_skip_image,
        disable_undo_last_action=disable_undo_last_action
    )

def get_progress_stat():
    """从文件动态加载 progress_stat"""
    if not hasattr(g, 'progress_stat'):
        progress_stat_path = osp.join(os.environ.get("DATASET_DIR"), 'progress_stat')  # 从环境变量获取路径
        if os.path.exists(progress_stat_path):
            with open(progress_stat_path, 'r') as f:
                g.progress_stat = json.load(f)
        else:
            # 如果文件不存在，初始化默认值并保存到文件
            g.progress_stat = {str(i): {'progress': 0, 'status': 'unprocessed', 'user': 'unselected'} for i in range(8)}
            save_json_data(g.progress_stat, progress_stat_path)
    return g.progress_stat

# 保存 progress_stat
def save_progress_stat(progress_stat):
    """保存 progress_stat 到文件"""
    progress_stat_path = osp.join(os.environ.get("DATASET_DIR"), 'progress_stat')
    save_json_data(progress_stat, progress_stat_path)

if __name__ == '__main__':
    # 使用 argparse 传递参数
    parser = argparse.ArgumentParser(description="Flask data filtering application.")
    parser.add_argument('--dir', type=str, required=True, help="Path to the directory containing the JSON file")
    parser.add_argument('--port', type=int, default=8860, help="Port to run the Flask application on (default: 8860)")
    parser.add_argument('--debug', action='store_true', help="Enable Flask debug mode for development")
    args = parser.parse_args()

    # 初始化全局变量
    load_or_initialize_global_data(args.dir)

    # 设置环境变量
    os.environ["DATASET_DIR"] = args.dir  # 数据集路径传递为环境变量

    app.run(host="0.0.0.0", port=args.port, debug=args.debug, threaded=True)