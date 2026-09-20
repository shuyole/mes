# -*- coding: utf-8 -*-
"""业务 API 蓝图汇总与注册模块。"""

from routes.auth import auth_bp


def register_routes(app):
    """把认证蓝图注册到 Flask 应用实例中。"""
    app.register_blueprint(auth_bp)


__all__ = ["register_routes", "auth_bp"]
