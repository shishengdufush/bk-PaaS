# -*- coding: utf-8 -*-
"""
Tencent is pleased to support the open source community by making 蓝鲸智云PaaS平台社区版 (BlueKing PaaS Community Edition) available.
Copyright (C) 2017-2018 THL A29 Limited, a Tencent company. All rights reserved.
Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at
http://opensource.org/licenses/MIT
Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.
""" # noqa

from __future__ import unicode_literals
import json

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from django.http import JsonResponse

from account.decorators import login_exempt
from common.utils import first_error_message
from common.log import logger
from common.responses import OKJsonResponse
from api.decorators import esb_required, esb_required_v2
from api.response import ApiV2FailJsonResponse, ApiV2OKJsonResponse
from api.constants import ApiErrorCodeEnumV2
from app.models import App
from home.models import UsefulLinks
from home.constants import LinkTypeEnum
from api.forms import (LightAppCreationForm, LightAppEditionForm,
                       LightAppChangeBaseInfoForm, LightAppLogoModifiedForm)
from api.utils import generate_file_by_base64


class AppInfoAPIView(View):
    """api to get app info
    @api {GET} /paas/api/app_info/ get_app_info
    @apiName get_app_info
    @apiGroup BK_PAAS
    @apiVersion 1.0.0
    @apiDescription 获取应用信息[支持批量获取]
    @apiParam (GET参数) {String} target_app_code 应用ID，多个target_app_code以英文分号分隔，target_app_code为空则表示所有应用
    @apiParamExample {json} 接口参数示例:
        {
            "target_app_code": "test1;test2",
        }
    @apiSuccessExample {json} Success-Response
        HTTP/1.1 200 OK
        {
            "result": true,
            "code": '00',
            "message": "SUCCESS",
            "data": [
                {
                    'app_code': 'test1',
                    'app_name': '测试1',
                },
                {
                    'app_code': 'test2',
                    'app_name': '测试2'
                }
            ]
        }
    """
    @method_decorator(csrf_exempt)
    @method_decorator(login_exempt)
    @method_decorator(esb_required)
    def dispatch(self, *args, **kwargs):
        return super(AppInfoAPIView, self).dispatch(*args, **kwargs)

    def get(self, request):
        # NOTE: better name is: target_app_codes
        app_codes = request.GET.get('target_app_code')

        query = App.objects.all()
        # 过滤查询的app_codes
        if app_codes:
            app_code_list = app_codes.split(';')

            query = query.filter(code__in=app_code_list)

        # 按照创建时间逆排序
        query = query.values('code', 'name').order_by('-created_date')
        app_list = [{
            'app_code': i['code'],
            'app_name': i['name']
        } for i in query]

        return OKJsonResponse("SUCCESS", data=app_list, code="00")


class AppInfoV2APIView(View):
    @method_decorator(csrf_exempt)
    @method_decorator(login_exempt)
    @method_decorator(esb_required_v2)
    def dispatch(self, *args, **kwargs):
        return super(AppInfoV2APIView, self).dispatch(*args, **kwargs)

    def get(self, request):
        app_codes = request.GET.get('target_app_code')
        fields = request.GET.get('fields')

        query = App.objects.all()
        # 过滤查询的app_codes
        if app_codes:
            app_code_list = app_codes.split(';')
            query = query.filter(code__in=app_code_list)
        extra_fields_set = set(fields.split(';')) & set(['introduction', 'creator', 'developer']) if fields else set()

        # 按照创建时间逆排序
        query = query.order_by('-created_date')
        app_list = []
        for app in query:
            item = {
                'bk_app_code': app.code,
                'bk_app_name': app.name
            }
            if 'introduction' in extra_fields_set:
                item.update({'introduction': app.introduction})
            if 'creator' in extra_fields_set:
                item.update({'creator': app.creater})
            if 'developer' in extra_fields_set:
                item.update({'developer': app.developer_str})
            app_list.append(item)

        return JsonResponse({
            "bk_error_msg": "",
            "bk_error_code": 0,
            "data": app_list
        })


class LightAppView(View):
    request_body_params = {}

    @method_decorator(csrf_exempt)
    @method_decorator(login_exempt)
    @method_decorator(esb_required_v2)
    def dispatch(self, request, *args, **kwargs):
        handler_map = {
            "create_app": "post",
            "edit_app": "put",
            "del_app": "delete",
            "modify_app_logo": "put_logo",
        }
        if request.method.lower() in self.http_method_names:
            handler_path = request.path.split('/')[-2]
            self.set_body_params(request, *args, **kwargs)
            handler = getattr(self, handler_map.get(handler_path), self.http_method_not_allowed)
        else:
            handler = self.http_method_not_allowed
        return handler(request, *args, **kwargs)

    def set_body_params(self, request, *args, **kwargs):
        try:
            self.request_body_params = json.loads(request.body) if request.body else {}
        except Exception:
            self.request_body_params = {}

    def post(self, request, *args, **kwargs):
        form = LightAppCreationForm(self.request_body_params)
        if not form.is_valid():
            message = first_error_message(form)
            return ApiV2FailJsonResponse(message, code=ApiErrorCodeEnumV2.PARAM_NOT_VALID.value)

        parent_app = App.objects.get(code=form.cleaned_data["bk_app_code"])

        # 保存应用信息到数据库
        link = UsefulLinks.objects.create(
            name=form.cleaned_data["bk_light_app_name"],
            link=form.cleaned_data["app_url"],
            link_type=LinkTypeEnum.SAAS.value,
            introduction=form.cleaned_data["introduction"] or parent_app.introduction
        )
        data = {'bk_light_app_code': link.code}

        return ApiV2OKJsonResponse("创建轻应用成功", data=data)

    def put(self, request, *args, **kwargs):
        form = LightAppEditionForm(self.request_body_params)
        if not form.is_valid():
            message = first_error_message(form)
            return ApiV2FailJsonResponse(message, code=ApiErrorCodeEnumV2.PARAM_NOT_VALID.value)

        is_ok, link = UsefulLinks.objects.is_useful_link(form.cleaned_data["bk_light_app_code"])

        # 保存应用基本信息
        introduction = form.cleaned_data["introduction"]
        link.introduction = introduction if introduction else link.introduction
        link.name = form.cleaned_data["bk_light_app_name"] if form.cleaned_data["bk_light_app_name"] else link.name
        link.link = form.cleaned_data["app_url"] if form.cleaned_data["app_url"] else link.link
        link.save()

        return ApiV2OKJsonResponse("app 修改成功", data={})

    def put_logo(self, request, *args, **kwargs):
        form = LightAppLogoModifiedForm(self.request_body_params)
        if not form.is_valid():
            message = first_error_message(form)
            return ApiV2FailJsonResponse(message, code=ApiErrorCodeEnumV2.PARAM_NOT_VALID.value)

        is_ok, link = UsefulLinks.objects.is_useful_link(form.cleaned_data["bk_light_app_code"])

        try:
            link.logo = generate_file_by_base64(form.cleaned_data["logo"])
            link.save()
        except Exception as e:
            # 保存logo时出错
            logger.exception(u"save app logo fail: %s" % e)
            return ApiV2FailJsonResponse("logo 数据格式不合法", code=ApiErrorCodeEnumV2.PARAM_NOT_VALID.value)

        return ApiV2OKJsonResponse("app logo修改成功", data={})

    def delete(self, request, *args, **kwargs):
        form = LightAppChangeBaseInfoForm(self.request_body_params)
        if not form.is_valid():
            message = first_error_message(form)
            return ApiV2FailJsonResponse(message, code=ApiErrorCodeEnumV2.PARAM_NOT_VALID.value)

        is_ok, link = UsefulLinks.objects.is_useful_link(form.cleaned_data["bk_light_app_code"])

        # 将app状态标记为下架
        link.is_active = False
        link.save()
        return ApiV2OKJsonResponse("app 下架成功", data={})
