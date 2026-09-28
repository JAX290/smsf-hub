# -*- coding: utf-8 -*-
"""应用包名 → 好认的名字。

手机端 SmsForwarder 转发通知时，取的字段是「包名」（NotificationService.kt 里
`val from = sbn.packageName`），模板里的 app 字段又是空的，所以服务端拿到的
只有 com.xxx.yyy 这种包名。这里做一层映射，面板上显示成中文名，方便按 APP 查看。

维护方式：直接在下面加一行即可；也可以在 config.yaml 的 panel.app_names 里覆盖。
没收录的包名原样显示，不影响使用。
"""

# 内置常见应用（按需增补）
BUILTIN = {
    # —— 实际出现过的 ——
    "com.ss.android.ugc.aweme": "抖音",
    "com.ss.android.article.news": "今日头条",
    "com.ss.android.article.lite": "头条极速版",
    "com.huawei.android.totemweather": "华为天气",
    "com.huawei.browser": "华为浏览器",
    "com.huawei.appmarket": "华为应用市场",
    "com.huawei.fastapp": "华为快应用",
    "com.huawei.gamebox": "华为游戏中心",
    "com.huawei.hiskytone": "华为主题",
    "com.huawei.phoneservice": "华为客服",
    "com.huawei.search": "华为搜索",
    "com.huawei.smarthome": "华为智慧生活",
    "com.huawei.android.hwouc": "系统更新",
    "com.huawei.systemmanager": "手机管家",
    "com.tencent.news": "腾讯新闻",
    "com.autonavi.minimap": "高德地图",
    "com.baidu.BaiduMap": "百度地图",
    "com.eg.android.AlipayGphone": "支付宝",
    "com.xiaomi.bsp.gps.nps": "小米定位服务",
    "cn.soulapp.android": "Soul",
    "com.lolaage.tbulu.tools": "途强在线",
    "com.android.settings": "系统设置",
    "com.android.mediacenter": "媒体中心",
    "com.android.incallui": "通话界面",
    "com.android.systemui": "系统界面",
    "com.android.packageinstaller": "应用安装器",
    "android": "系统",
    "com.google.android.gms": "谷歌服务",
    "com.xiaomi.mi_connect_service": "小米互联服务",
    # —— 常见补充 ——
    "com.tencent.mm": "微信",
    "com.tencent.mobileqq": "QQ",
    "com.sina.weibo": "微博",
    "com.taobao.taobao": "淘宝",
    "com.tmall.wireless": "天猫",
    "com.jingdong.app.mall": "京东",
    "com.xunmeng.pinduoduo": "拼多多",
    "com.achievo.vipshop": "唯品会",
    "com.sankuai.meituan": "美团",
    "me.ele": "饿了么",
    "com.sdu.didi.psnger": "滴滴出行",
    "com.MobileTicket": "铁路12306",
    "com.zhihu.android": "知乎",
    "com.smile.gifmaker": "快手",
    "com.xingin.xhs": "小红书",
    "tv.danmaku.bili": "哔哩哔哩",
    "com.netease.cloudmusic": "网易云音乐",
    "com.tencent.qqmusic": "QQ音乐",
    "com.ximalaya.ting.android": "喜马拉雅",
    "com.qiyi.video": "爱奇艺",
    "com.tencent.qqlive": "腾讯视频",
    "com.youku.phone": "优酷",
    "com.netease.newsreader.activity": "网易新闻",
    "com.ss.android.ugc.live": "抖音火山版",
    "com.kuaishou.nebula": "快手极速版",
    "com.unionpay": "云闪付",
    "com.icbc": "工商银行",
    "com.ccb.longjiLife": "建设银行",
    "com.chinamobile.android.andlink": "中国移动",
    "com.tencent.wework": "企业微信",
    "com.alibaba.android.rimet": "钉钉",
    "com.xuexiang.xqkc": "学习强国",
    "com.microsoft.office.officehubrow": "Office",
    "com.tencent.mtt": "QQ浏览器",
    "com.UCMobile": "UC浏览器",
    "com.quark.browser": "夸克浏览器",
    "com.baidu.searchbox": "百度",
    "com.ss.android.ugc.aweme.lite": "抖音极速版",
}


def build_map(override=None) -> dict:
    """合并内置表与配置覆盖（配置优先）。"""
    m = dict(BUILTIN)
    if isinstance(override, dict):
        for k, v in override.items():
            if k and v:
                m[str(k)] = str(v)
    return m


def display_name(pkg: str, table: dict) -> str:
    """包名 → 显示名；查不到就原样返回。"""
    p = (pkg or "").strip()
    if not p:
        return ""
    return table.get(p) or table.get(p.lower()) or p
