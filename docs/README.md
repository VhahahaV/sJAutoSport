# 文档目录

本目录包含了 SJTU 体育预订系统的所有文档，按功能分类整理。

## 📁 目录结构

```
docs/
├── README.md                    # 本文档索引
├── guides/                      # 使用指南
│   ├── AUTO_BOOKING_GUIDE.md   # 自动抢票系统使用指南
│   ├── QUICK_START.md          # 快速开始指南
│   ├── bot_README.md           # 机器人系统说明
│   └── CATNAPQQ_SETUP.md       # CatNapQQ 配置指南
├── summaries/                   # 项目总结
│   ├── AUTO_BOOKING_SUMMARY.md # 自动抢票系统实施总结
│   ├── ENHANCED_FEATURES_SUMMARY.md # 增强功能实施总结
│   └── IMPLEMENTATION_SUMMARY.md    # 项目实现总结
├── api/                        # API文档
│   └── SJTU_SECRET_ORDER.md   # 加密/解密技术分析
└── examples/                   # 示例代码
    └── (待添加)
```

## 📚 文档说明

### 使用指南 (guides/)

- **AUTO_BOOKING_GUIDE.md**: 自动抢票系统的详细使用指南，包括配置、命令、故障排除等
- **QUICK_START.md**: 项目的快速开始指南，帮助用户快速上手
- **bot_README.md**: 机器人系统的说明文档，包括插件配置和使用方法
- **CATNAPQQ_SETUP.md**: CatNapQQ 配置指南，包括安装、配置和连接步骤

### 项目总结 (summaries/)

- **AUTO_BOOKING_SUMMARY.md**: 自动抢票系统的完整实施总结，包括技术架构、功能特性、性能指标等
- **ENHANCED_FEATURES_SUMMARY.md**: 增强功能的实施总结，包括插件系统、数据库持久化、验证码处理等
- **IMPLEMENTATION_SUMMARY.md**: 整个项目的实现总结，包括核心功能、技术栈、部署说明等

### API文档 (api/)

- **SJTU_SECRET_ORDER.md**: SJTU体育预约系统加密/解密技术分析，包括AES/RSA加密实现、逆向工程方法论等

### 示例代码 (examples/)

- 待添加：使用示例和代码片段

## 🚀 快速导航

### 新用户
1. 先阅读 [快速开始指南](guides/QUICK_START.md)
2. 了解 [机器人系统](guides/bot_README.md)
3. 配置 [自动抢票系统](guides/AUTO_BOOKING_GUIDE.md)

### 开发者
1. 查看 [项目实现总结](summaries/IMPLEMENTATION_SUMMARY.md)
2. 了解 [增强功能](summaries/ENHANCED_FEATURES_SUMMARY.md)
3. 研究 [自动抢票系统](summaries/AUTO_BOOKING_SUMMARY.md)
4. 学习 [加密技术分析](api/SJTU_SECRET_ORDER.md)

### 运维人员
1. 参考 [自动抢票指南](guides/AUTO_BOOKING_GUIDE.md) 进行部署
2. 查看 [项目总结](summaries/IMPLEMENTATION_SUMMARY.md) 了解架构
3. 使用 [快速开始](guides/QUICK_START.md) 进行测试

## 📝 文档维护

- 所有文档使用 Markdown 格式
- 保持文档的及时更新
- 添加新功能时同步更新相关文档
- 定期检查文档的准确性和完整性

## 🔗 相关链接

- 项目根目录: [../README.md](../README.md)
- 配置文件: [../config.py](../config.py)
- 核心代码: [../sja_booking/](../sja_booking/)
- 机器人代码: [../bot/](../bot/)
