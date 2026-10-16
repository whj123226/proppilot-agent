# 参与贡献

欢迎提交可复现的问题、文档修正和小范围改进。请先阅读README和docs/ARCHITECTURE.md，当前网页入口是web_app.py。

## 提交问题

请注明Python和MySQL版本、fixture或live模式、复现步骤、预期与实际行为。日志只保留排查所需的错误类型及匿名编号，不上传.env、模型密钥、Cookie、数据库凭证、个人资料或客户业务数据。

## 本地检查

```sh
python -m pip install -r requirements-web.txt
python -B -m unittest discover -s tests -v
```

未配置MySQL时6项集成测试会明确跳过；需要验证集成行为时使用具有创建和删除测试库权限的本机测试账号。测试只清理自己创建的随机测试库，不要使用生产数据库或生产凭证。普通回归不调用付费模型。

功能修改需写清触发场景、行为变化和实际验证结果。涉及状态恢复、任务所有权或工单写入时，补充相应回归证据。live、Docker与公网测试分别注明是否运行，不用fixture结果代替。

提交内容按本项目MIT许可证发布；第三方代码、文档和素材需确认来源及许可。
