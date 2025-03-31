from pkg.plugin.context import register, handler, llm_func, BasePlugin, APIHost, EventContext
from pkg.plugin.events import *  # 导入事件类
from datetime import datetime, timedelta, timezone
import asyncio
import pkg.platform.types as platform_types
import openai
from openai import OpenAI
from typing import Union
import httpx
import os
import aiohttp

class TargetInfo(object):
    def __init__(self, target_id: str, target_type: str, sender_id: str):
        # QQ群群号或者QQ号
        self.target_id = target_id
        # person或者group。person表示私聊，group表示群聊
        self.target_type = target_type
        # 发送者QQ号
        self.sender_id = sender_id

# 注册插件
@register(name="Scheduler", description="自定义各种定时任务", version="0.1", author="AlphaXdream")
class SchedulerPlugin(BasePlugin):
    # 消息平台的域名,端口号和token
    # 使用时需在napcat内配置http服务器 host和port对应好
    http_host = "napcat"
    http_port = 2333
    # 若消息平台未配置token则留空 否则填写配置的token
    token = ""
    # 上传到群文件的哪个目录?默认"/"是传到根目录 如果指定目录要提前在群文件里建好文件夹
    group_folder = "/"

    client: openai.AsyncClient = None
    data: dict = {}
    # 插件加载时触发
    def __init__(self, host: APIHost):
        pass

    # 异步初始化
    async def initialize(self):
        self.ap.logger.info(f"SchedulerPlugin init {id(self)}")

    # 当收到个人消息时触发
    @handler(PersonNormalMessageReceived)
    async def person_normal_message_received(self, ctx: EventContext):
        ctx.prevent_default()
        
        msg = ctx.event.text_message  # 这里的 event 即为 PersonNormalMessageReceived 的对象
        target_info = TargetInfo(str(ctx.event.launcher_id), str(ctx.event.launcher_type).split(".")[-1].lower(), str(ctx.event.sender_id))
        commands = msg.split(" ")
        if commands[0] != "sched":
            await self.send_message(target_info, f"Test Person Message launcher_id:{ctx.event.launcher_id}, launcher_type: {ctx.event.launcher_type}, sender_id:{ctx.event.sender_id}")
            return


        command = commands[1]
        if command == "testfile":
            await self.send_file(target_info, "daily.txt")
            ctx.prevent_default()
            return
        
        if command == "daily":
            # 输出调试信息
            self.ap.logger.info("daily, classId:{}, {}".format(id(self), ctx.event.sender_id))

            if len(commands) > 2:
                await self.do_daily_task("Daily training Start Immediately!")
                ctx.prevent_default()
                return

            if self.data.get(str(ctx.event.sender_id)) is None:
                self.data[str(ctx.event.sender_id)] = {}
                self.data[str(ctx.event.sender_id)]["daily"] = True
                self.data[str(ctx.event.sender_id)]["daily_time"] = "02:00"
                self.data[str(ctx.event.sender_id)]["info"] = target_info
            else:
                ctx.add_return("reply", ["已设置每日任务, 不用重复设置!"])
                ctx.prevent_default()
                return

            #【错峰优惠活动】北京时间每日 00:30-08:30 为错峰时段，API 调用价格大幅下调：
            # DeepSeek-V3 降至原价的 50%，DeepSeek-R1 降至 25%，在该时段调用享受更经济更流畅的服务体验。
            self.data[target_info.sender_id]["task"] = asyncio.create_task(self.schedule_daily_task(target_info, "Daily training Start!", "02:00"))
            # 回复消息 "hello, <发送者id>!"
            ctx.add_return("reply", ["已设置每日任务!"])


        # 阻止该事件默认行为（向接口获取回复）
        ctx.prevent_default()

    # 当收到群消息时触发
    @handler(GroupNormalMessageReceived)
    async def group_normal_message_received(self, ctx: EventContext):
        msg = ctx.event.text_message  # 这里的 event 即为 GroupNormalMessageReceived 的对象
        if msg == "hello":  # 如果消息为hello

            # 输出调试信息
            self.ap.logger.info("hello, classId:{}, {}".format(id(self), ctx.event.sender_id))

            # 回复消息 "hello, everyone!"
            ctx.add_return("reply", ["hello, everyone!"])
            target_info = TargetInfo(str(ctx.event.launcher_id), str(ctx.event.launcher_type).split(".")[-1].lower(), str(ctx.event.sender_id))
            await self.send_message(target_info, f"Test Group Message launcher_id:{ctx.event.launcher_id}, launcher_type: {ctx.event.launcher_type}, sender_id:{ctx.event.sender_id}")

        # 阻止该事件默认行为（向接口获取回复）
        ctx.prevent_default()

    async def chat_with_gpt(self, prompt: str, temperature: float = 0.7) -> Union[str, None]:
        if self.client is None:
            requester_cfg = self.ap.provider_cfg.data['requester']['deepseek-chat-completions']
            self.client = openai.AsyncClient(
                api_key=self.ap.provider_cfg.data["keys"]["deepseek"][0],
                base_url=requester_cfg['base-url'],
                timeout=requester_cfg['timeout'],
                http_client=httpx.AsyncClient(
                    trust_env=True,
                    timeout=requester_cfg['timeout']
                )
            )
        response = await self.client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a helpful assistant"},
                {"role": "user", "content": prompt},
            ],
            stream=False
        )
        return response.choices[0].message.content

    # 按行读取文件
    def read_file_by_line(self, file_path):
        file_path = os.path.join(os.path.dirname(__file__), file_path)
        lines = []
        with open(file_path, 'r', encoding='utf-8') as file:
            for line in file:
                line = line.strip()
                if line == "":
                    continue
                lines.append(line)
        return lines
    async def schedule_daily_task(self, target_info: TargetInfo, messages: str, daily_time: str):
        """
        Schedule a task to send a message at a fixed daily time.

        :param messages: The message to be sent.
        :param daily_time: The time of day to send the message, in "HH:MM" format.
        """
        tz = timezone(timedelta(hours=8))  # Define the timezone for UTC+8
        while True:
            now = datetime.now(tz)
            # Parse the target time for today in UTC+8
            target_time = datetime.strptime(daily_time, "%H:%M").replace(year=now.year, month=now.month, day=now.day, tzinfo=tz)
            
            # If the target time has already passed today, schedule for the next day
            if now > target_time:
                target_time += timedelta(days=1)
            
            # Calculate the number of seconds to wait until the target time
            wait_seconds = (target_time - now).total_seconds()
            self.ap.logger.info("schedule wait {}s, {}".format(wait_seconds, target_info.sender_id))
            await asyncio.sleep(wait_seconds)
            await self.do_daily_task(messages)

            # Send the scheduled message
            # TODO: 支持多人
            # await self.send_message(messages)

    async def do_daily_task(self, target_info:TargetInfo, messages: str):
        await self.send_message(messages)
        messages = None
        prompts = self.read_file_by_line("daily.txt")
        index = 1
        for prompt in prompts:
            file_content = ""
            while True:
                try:
                    if messages is None:
                        response = await self.chat_with_gpt(prompt)
                        messages = f"{index}. {prompt}\n{response}"
                    # await self.send_message(messages)
                    file_content = file_content + messages + "\n\n"
                    index += 1
                    messages = None
                    break
                except Exception as e:
                    self.ap.logger.error(f"Error occurred while chatting with GPT: {e}")
                    await asyncio.sleep(15)
            
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        output_file_name = f"{timestamp}_daily.txt"
        output_file_path = os.path.join(os.path.dirname(__file__), output_file_name)
        with open(output_file_path, "w", encoding="utf-8") as output_file:
            output_file.write(file_content)
        await self.send_file(target_info, output_file_name)

    async def send_message(self, target_info:TargetInfo, messages: str):
        # Send the scheduled message
        await self.host.send_active_message(
            adapter=self.host.get_platform_adapters()[0],
            target_type=target_info.target_type,
            target_id=target_info.target_id,
            message=platform_types.MessageChain([platform_types.At(target_info.sender_id),
                platform_types.Plain(messages)
            ])
        )

    async def send_file(self, target_info: TargetInfo, relpath: str):
        file_path = os.path.join(os.path.dirname(__file__), relpath)
        if not os.path.exists(file_path):
            self.ap.logger.error(f"File not found: {file_path}")
            return
        
        file_name = os.path.basename(file_path)
        # 需要在napcat安装和配置好sshd，langbot安装ssh（自带了scp）
        target_machine = "napcat:/tmp/"
        command = f"scp {file_path} {target_machine}"
        os.system(command)
        await self.upload_private_file(target_info.sender_id, "/tmp/" + file_name, file_name)
        # await self.host.send_active_message(
        #     adapter=self.host.get_platform_adapters()[0],
        #     target_type=target_info.target_type,
        #     target_id=target_info.target_id,
        #     message=platform_types.MessageChain([platform_types.At(target_info.sender_id),
        #         platform_types.File(file_path)
        #     ])
        # )

    # 感谢 https://github.com/exneverbur/ShowMeJM
    # 发送私聊文件
    async def upload_private_file(self, user_id, file, name):
        url = f"http://{self.http_host}:{self.http_port}/upload_private_file"
        payload = {
            "user_id": user_id,
            "file": file,
            "name": name
        }
        if self.token == "":
            headers = {
                'Content-Type': 'application/json'
            }
        else:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.token}'
            }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status != 200:
                    raise Exception(f"上传失败，状态码: {response.status}, 错误信息: {response.text}")
                res = await response.json()
                print("napcat返回消息->" + str(res))
                if res["status"] != "ok":
                    raise Exception(f"上传失败，状态码: {res['status']}, 描述: {res['message']}\n完整消息: {str(res)}")

    # 发送群文件
    async def upload_group_file(self, group_id, file, name):
        url = f"http://{self.http_host}:{self.http_port}/upload_group_file"
        payload = {
            "group_id": group_id,
            "file": file,
            "name": name,
            "folder_id": self.group_folder
        }
        if self.token == "":
            headers = {
                'Content-Type': 'application/json'
            }
        else:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.token}'
            }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status != 200:
                    raise Exception(f"上传失败，状态码: {response.status}, 错误信息: {response.text}")
                res = await response.json()
                print("napcat返回消息->" + str(res))
                if res["status"] != "ok":
                    raise Exception(f"上传失败，状态码: {res['status']}, 描述: {res['message']}\n完整消息: {str(res)}")


    # 插件卸载时触发
    def __del__(self):
        self.ap.logger.info(f"SchedulerPlugin del {id(self)}")
        for key in self.data:
            if self.data[key].get("task") is not None:
                self.data[key]["task"].cancel()
        self.data.clear()
        if self.client is not None:
            self.client.close()
            self.client = None
