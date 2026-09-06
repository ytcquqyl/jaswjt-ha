# 吉安水务 - Home Assistant 自定义集成

Home Assistant custom integration for 吉安水务 (Ji'an Water Service).

## 功能

- 查询多个户号的水费账单
- 当月水费、用水量、余额等实时数据
- 历史月份用水量和费用记录
- 欠费状态提醒
- JSESSIONID 自动续命（15分钟轮询）

## 安装

1. 在 Home Assistant 中安装 [HACS](https://hacs.xyz/)
2. 在 HACS 中搜索并安装此集成
3. 重启 Home Assistant
4. 进入 设置 → 设备与服务 → 添加集成 → 吉安水务
5. 输入 JSESSIONID 和户号

## JSESSIONID 获取方法

1. 在手机上安装 Charles 或 Fiddler 抓包工具
2. 打开吉安水务微信小程序
3. 找到 `method=userinfo` 请求
4. 从响应头 `Set-Cookie` 中提取 `JSESSIONID=xxx` 的值

## 配置

- **JSESSIONID**: 从微信抓包获取
- **户号**: 多个户号用逗号分隔，例如 `12345678, 87654321`

## License

MIT
