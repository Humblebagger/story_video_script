"""内容限制的类别代码（界面文案在消息登记表的 safety.category.<code>）与策略版本。"""

CLASSIFIER_CODES = ("sexual", "minor_sexual", "drugs", "political", "extremism")   # 分类器只能给这五类
UNSPECIFIED = "unspecified"                                                        # 底层模型服务拒绝处理
CODES = CLASSIFIER_CODES + (UNSPECIFIED,)

# 分类系统提示的版本：改了尺度就加一，旧的结论缓存自动失效（放行过的条目不失效）
POLICY_VERSION = "1"
