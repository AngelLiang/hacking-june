# coding=utf-8
import time
import base64
import hashlib
import functools
from flask import g, request, session, current_app
from flask import flash, url_for, redirect, abort
from flask.ext.babel import lazy_gettext as _
from .models import Account, cache


class require_role(object):
    """
    角色类装饰器
    """

    # 角色权限等级
    roles = {
        'spam': 0,
        'new': 1,
        'user': 2,
        'staff': 3,
        'admin': 4,
    }

    def __init__(self, role):
        self.role = role

    def __call__(self, method):
        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            if not g.user:
                url = url_for('account.signin')
                if '?' not in url:
                    url += '?next=' + request.url
                return redirect(url)
            if self.role is None:
                return method(*args, **kwargs)
            if g.user.id == 1:
                # this is superuser, have no limitation
                return method(*args, **kwargs)
            if g.user.role == 'new':
                flash(_('Please verify your email'), 'warn')
                return redirect(url_for('account.setting'))
            if g.user.role == 'spam':
                flash(_('You are a spammer'), 'error')
                return redirect('/')
            # 判断角色权限
            if self.roles[g.user.role] < self.roles[self.role]:
                return abort(403)
            return method(*args, **kwargs)
        return wrapper


require_login = require_role(None)
require_user = require_role('user')
require_staff = require_role('staff')
require_admin = require_role('admin')


class limit_request(object):
    """
    Limitations on user requests.

    :param seconds: next request should be after N seconds
    :param prefix: cache key prefix
    :param method: the method of the request
    :param redirect_url: redirect when exceeding limited time

    The redirect_url can be a string or function. When it is a function,
    it accepts the same parameters as the wrapped methods.
    """

    """
    请求限制器
    """

    def __init__(self, seconds=0, prefix=None, method='POST',
                 redirect_url=None):
        self.seconds = seconds
        self.prefix = prefix
        self.method = method
        self.redirect_url = redirect_url

    def __call__(self, method):
        """
        :param method: 方法，其实就是一个被装饰的函数
        """
        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            if request.method != self.method:
                return method(*args, **kwargs)

            if not g.user:
                return abort(403)

            prefix = self.prefix
            if prefix is None:
                prefix = request.path

            # cache key，应该使用英文冒号分隔
            key = '%s-%s-%i' % (prefix, self.method, g.user.id)

            now = time.time()
            # cache: flask.ext.cache
            last_cached = cache.get(key)  # 获取缓存
            # 缓存命中并且没有超时
            if last_cached and (now - last_cached) < self.seconds:
                flash(_('Too many requests in a time'), 'warn')
                # URL重定向
                redirect_url = self.redirect_url or request.url
                if callable(redirect_url):
                    redirect_url = redirect_url(*args, **kwargs)
                return redirect(redirect_url)
            # 设置缓存，应该也要设置缓存超时时间
            cache.set(key, now)  
            return method(*args, **kwargs)
        return wrapper


def get_current_user():
    # session: flask.session
    if 'id' in session and 'token' in session:
        user = Account.query.get(int(session['id']))
        if not user:
            return None
        if user.token != session['token']:
            return None
        return user
    return None


def login_user(user, permanent=False):
    """
    :param user:
    :param permanent: bool, 记住我功能？
    """
    if not user:
        return None
    session['id'] = user.id
    session['token'] = user.token
    if permanent:
        session.permanent = True
    return user


def logout_user():
    if 'id' not in session:
        return
    session.pop('id')
    session.pop('token')


def create_auth_token(user):
    """
    :param user:
    """
    timestamp = int(time.time())
    secret = current_app.secret_key
    token = '%s%s%s%s' % (secret, timestamp, user.id, user.token)
    hsh = hashlib.sha1(token).hexdigest()  # 生成hash进行加签
    # token没有加密，只是进行了base64
    return base64.b32encode('%s|%s|%s' % (timestamp, user.id, hsh))


def verify_auth_token(token, expires=30):
    """
    :param token: str
    :param expires: int, 过期时间
    """
    try:
        token = base64.b32decode(token)
    except:
        return None
    bits = token.split('|')
    if len(bits) != 3:
        return None
    timestamp, user_id, hsh = bits
    try:
        timestamp = int(timestamp)
        user_id = int(user_id)
    except:
        return None
    delta = time.time() - timestamp
    if delta < 0:
        return None
    if delta > expires * 60 * 60 * 24:
        return None
    user = Account.query.get(user_id)
    if not user:
        return None
    # 验签
    secret = current_app.secret_key
    _hsh = hashlib.sha1('%s%s%s%s' % (secret, timestamp, user_id, user.token))
    if hsh == _hsh.hexdigest():
        return user
    return None


def force_int(value, default=1):
    try:
        return int(value)
    except:
        return default
