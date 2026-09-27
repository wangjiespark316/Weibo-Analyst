"""
行业标签库配置
包含各行业的关注技术、适合场景、推荐产品

说明：
- 每个行业支持 aliases（别名），用于匹配飞书 CRM 中口径不一的行业名称；
- get_industry_by_name 依次按「精确名称 → 别名精确 → 关键词包含」匹配；
- 场景/推荐产品为销售方法论配置（专家知识），不是业务数据，不涉及造假。
"""

INDUSTRIES = [
    {
        "name": "制造业",
        "aliases": ["制造", "生产制造", "加工厂", "生产", "代工"],
        "key_technologies": ["AI质检", "知识库", "流程自动化", "Agent", "预测性维护"],
        "scenarios": ["智能质检", "设备维护知识库", "生产流程优化", "供应链管理", "工人培训"],
        "recommended_products": ["飞书", "豆包", "Agent"],
        "customer_type": "100-5000人制造企业",
        "pain_points": ["质检效率低", "知识传承难", "流程不透明", "设备故障停机"]
    },
    {
        "name": "互联网",
        "aliases": ["互联网媒体", "网络科技", "互联网公司", "在线平台", "平台经济"],
        "key_technologies": ["AI编程", "大模型", "Agent", "多模态", "RAG"],
        "scenarios": ["代码辅助开发", "智能客服", "内容生成", "用户分析", "产品迭代"],
        "recommended_products": ["豆包", "飞书", "Copilot"],
        "customer_type": "互联网公司/创业团队",
        "pain_points": ["开发效率", "用户增长", "内容生产", "数据驱动决策"]
    },
    {
        "name": "企业服务",
        "aliases": ["B2B服务", "专业服务", "咨询服务", "商务服务", "现代服务业"],
        "key_technologies": ["AI办公", "Agent", "知识库", "流程自动化", "RAG"],
        "scenarios": ["智能客服", "企业知识库", "销售/审批流程自动化", "销售助手", "会议纪要与总结"],
        "recommended_products": ["飞书", "豆包", "Agent"],
        "customer_type": "100-10000人 B2B/专业服务企业",
        "pain_points": ["人力成本高", "知识沉淀难", "流程依赖人工", "销售人效低"]
    },
    {
        "name": "传媒广告",
        "aliases": ["传媒", "广告", "媒体", "公关", "内容营销", "营销策划", "MCN", "文化传媒"],
        "key_technologies": ["AIGC内容生成", "多模态", "AI视频", "AI绘画", "大模型"],
        "scenarios": ["营销文案生成", "素材/短视频生成", "舆情监测", "选题策划", "客户提案"],
        "recommended_products": ["豆包", "飞书"],
        "customer_type": "传媒/广告/营销/内容机构",
        "pain_points": ["内容产能不足", "人力成本高", "热点响应慢", "创意同质化"]
    },
    {
        "name": "汽车",
        "aliases": ["汽车制造", "主机厂", "整车厂", "新能源车", "汽车零部件", "汽车零部件制造"],
        "key_technologies": ["AI质检", "知识库", "自动驾驶", "智能座舱", "流程自动化"],
        "scenarios": ["产线智能质检", "研发知识库", "供应链协同", "经销商智能客服", "车端语音助手"],
        "recommended_products": ["飞书", "豆包", "Agent"],
        "customer_type": "整车厂/零部件/汽车服务企业",
        "pain_points": ["质检与合规压力大", "研发知识分散", "供应链协同复杂", "渠道服务参差"]
    },
    {
        "name": "教育",
        "aliases": ["培训", "学校", "在线教育", "教育机构", "培训机构", "K12", "职业教育"],
        "key_technologies": ["AI教学", "知识库", "多模态", "个性化学习", "智能批改"],
        "scenarios": ["智能备课", "个性化辅导", "作业批改", "教学知识库", "学生评估"],
        "recommended_products": ["豆包", "飞书"],
        "customer_type": "学校/教育机构/培训机构",
        "pain_points": ["师资不足", "个性化难", "批改工作量大", "教学资源分散"]
    },
    {
        "name": "医疗",
        "aliases": ["医药", "医疗服务", "医院", "医药研发", "医药行业", "生物医药", "医疗器械", "健康", "医疗健康", "CRO"],
        "key_technologies": ["医疗AI", "知识库", "RAG", "多模态", "智能问诊"],
        "scenarios": ["病历分析", "医学知识库", "智能辅助诊断", "患者随访", "医药研发信息检索"],
        "recommended_products": ["飞书", "豆包"],
        "customer_type": "医院/医疗机构/医药与医疗科技公司",
        "pain_points": ["病历整理", "知识更新快", "医患沟通", "研发与合规信息量大"]
    },
    {
        "name": "零售",
        "aliases": ["电商", "连锁", "商超", "便利店", "品牌零售", "零售连锁", "新零售"],
        "key_technologies": ["AI客服", "用户分析", "推荐系统", "Agent", "智能营销"],
        "scenarios": ["智能客服", "用户画像", "商品推荐", "营销内容生成", "门店管理"],
        "recommended_products": ["豆包", "飞书"],
        "customer_type": "零售企业/电商/品牌方",
        "pain_points": ["客服成本高", "用户体验", "库存管理", "营销效率"]
    },
    {
        "name": "酒店餐饮",
        "aliases": ["酒店", "餐饮连锁", "餐饮", "饭店", "连锁餐饮", "文旅", "酒店管理", "餐饮管理"],
        "key_technologies": ["智能客服", "会员营销", "知识库", "AI客服", "运营分析"],
        "scenarios": ["智能预订与客服", "会员个性化营销", "门店运营知识库", "员工培训", "评价舆情分析"],
        "recommended_products": ["飞书", "豆包"],
        "customer_type": "酒店/连锁餐饮/文旅服务企业",
        "pain_points": ["人力流动大", "服务标准难统一", "会员复购低", "多店管理难"]
    },
    {
        "name": "美业生活服务",
        "aliases": ["综合美容院", "美容", "美发", "美业", "生活服务", "家政", "康养服务"],
        "key_technologies": ["智能客服", "会员管理", "智能营销", "知识库"],
        "scenarios": ["会员智能营销", "预约与客服自动化", "技师培训知识库", "评价管理"],
        "recommended_products": ["豆包", "飞书"],
        "customer_type": "美容/美业/本地生活连锁",
        "pain_points": ["获客成本高", "会员复购低", "技师流动大", "服务标准化难"]
    },
    {
        "name": "贸易",
        "aliases": ["外贸", "进出口", "跨境", "跨境电商", "国际贸易"],
        "key_technologies": ["AI翻译", "知识库", "Agent", "市场分析", "智能文档"],
        "scenarios": ["多语言沟通", "客户管理", "市场调研", "合同文档处理", "供应链协调"],
        "recommended_products": ["飞书", "豆包", "翻译工具"],
        "customer_type": "外贸企业/进出口公司",
        "pain_points": ["语言障碍", "客户分散", "信息不对称", "文档繁琐"]
    },
    {
        "name": "物流",
        "aliases": ["快递", "运输", "仓储", "供应链", "物流运输", "货运"],
        "key_technologies": ["路径优化", "预测分析", "Agent", "知识库", "智能调度"],
        "scenarios": ["智能调度", "路径规划", "仓储管理", "客户服务", "异常处理"],
        "recommended_products": ["飞书", "豆包"],
        "customer_type": "物流企业/快递公司/仓储企业",
        "pain_points": ["调度复杂", "成本高", "异常处理慢", "信息不透明"]
    },
    {
        "name": "金融",
        "aliases": ["金融投资", "银行", "证券", "保险", "投资", "基金", "金融科技", "资管"],
        "key_technologies": ["风控AI", "知识库", "RAG", "智能投顾", "合规分析"],
        "scenarios": ["风险控制", "智能客服", "投研分析", "合规审查", "客户管理"],
        "recommended_products": ["飞书", "豆包"],
        "customer_type": "银行/证券/保险/金融科技公司",
        "pain_points": ["风控难度大", "合规要求高", "客户服务", "投研效率"]
    },
    {
        "name": "软件开发",
        "aliases": ["高科技研发", "软件", "IT", "信息技术", "SaaS", "科技研发", "软件信息", "技术服务"],
        "key_technologies": ["AI编程", "Agent", "代码审查", "知识库", "自动化测试"],
        "scenarios": ["代码辅助", "需求分析", "测试自动化", "技术文档", "团队协作"],
        "recommended_products": ["豆包", "飞书", "Copilot"],
        "customer_type": "软件公司/IT部门/研发团队",
        "pain_points": ["开发效率", "代码质量", "文档维护", "知识传承"]
    },
    {
        "name": "建筑",
        "aliases": ["工程", "房地产", "地产", "建设", "建筑工程", "施工"],
        "key_technologies": ["AI识图", "知识库", "流程自动化", "安全监控", "项目管理"],
        "scenarios": ["安全检查", "图纸识别", "项目管理", "施工知识库", "材料管理"],
        "recommended_products": ["飞书", "豆包"],
        "customer_type": "建筑公司/工程企业/房地产企业",
        "pain_points": ["安全管理", "项目复杂", "信息分散", "知识传承"]
    }
]


def get_all_industries():
    """获取所有行业列表"""
    return INDUSTRIES


def get_industry_by_name(name):
    """根据名称获取行业信息：精确名称 → 别名精确 → 关键词包含。"""
    if not name:
        return None
    name = str(name).strip()
    # 1. 名称精确匹配
    for industry in INDUSTRIES:
        if industry["name"] == name:
            return industry
    # 2. 别名精确匹配
    for industry in INDUSTRIES:
        if name in industry.get("aliases", []):
            return industry
    # 3. 关键词包含匹配（命中的别名越长/越具体，优先级越高）
    candidates = []
    for industry in INDUSTRIES:
        keys = [industry["name"]] + industry.get("aliases", [])
        for k in keys:
            if k and (k in name or name in k):
                candidates.append((len(k), industry))
                break
    if candidates:
        candidates.sort(key=lambda x: -x[0])
        return candidates[0][1]
    return None


def get_industry_names():
    """获取所有行业名称"""
    return [industry["name"] for industry in INDUSTRIES]


def match_industry_by_technology(technology):
    """根据技术匹配相关行业"""
    matched = []
    for industry in INDUSTRIES:
        if any(tech in technology or technology in tech for tech in industry["key_technologies"]):
            matched.append(industry["name"])
    return matched


def match_industry_by_scenario(scenario):
    """根据场景匹配相关行业"""
    matched = []
    for industry in INDUSTRIES:
        if any(sc in scenario or scenario in sc for sc in industry["scenarios"]):
            matched.append(industry["name"])
    return matched
