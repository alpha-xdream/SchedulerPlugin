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

# 注册插件
@register(name="Scheduler", description="自定义各种定时任务", version="0.1", author="AlphaXdream")
class SchedulerPlugin(BasePlugin):
    client: openai.AsyncClient = None
    data: dict = {}
    # 插件加载时触发
    def __init__(self, host: APIHost):
        self.ap.logger.info("SchedulerPlugin init")

    # 异步初始化
    async def initialize(self):
        pass

    # 当收到个人消息时触发
    @handler(PersonNormalMessageReceived)
    async def person_normal_message_received(self, ctx: EventContext):
        msg = ctx.event.text_message  # 这里的 event 即为 PersonNormalMessageReceived 的对象
        if msg == "daily":
            if self.data.get(str(ctx.event.sender_id)) is None:
                self.data[str(ctx.event.sender_id)] = {}
                self.data[str(ctx.event.sender_id)]["daily"] = True
                self.data[str(ctx.event.sender_id)]["daily_time"] = "02:00"
            else:
                ctx.add_return("reply", ["已设置每日任务, 不用重复设置!"])
                ctx.prevent_default()
                return

            # 输出调试信息
            self.ap.logger.info("daily, classId:{}, {}".format(id(self), ctx.event.sender_id))

            target_info = {
            "target_id": str(ctx.event.launcher_id),
            "sender_id": str(ctx.event.sender_id),
            "target_type": str(ctx.event.launcher_type).split(".")[-1].lower(),  # 获取枚举值的小写形式
            }
            self.target_id = target_info["target_id"]
            self.target_type = target_info["target_type"]
            self.sender_id = target_info["sender_id"]

            #【错峰优惠活动】北京时间每日 00:30-08:30 为错峰时段，API 调用价格大幅下调：
            # DeepSeek-V3 降至原价的 50%，DeepSeek-R1 降至 25%，在该时段调用享受更经济更流畅的服务体验。
            self.data[self.sender_id]["task"] = asyncio.create_task(self.schedule_daily_task("Daily training Start!", "02:00"))
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
    async def schedule_daily_task(self, messages: str, daily_time: str):
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
            self.ap.logger.info("schedule wait {}s, {}".format(wait_seconds, self.sender_id))
            await asyncio.sleep(wait_seconds)
            await self.send_message(messages)
            
            prompts = self.read_file_by_line("daily.txt")
            index = 0
            for prompt in prompts:
                while True:
                    try:
                        response = await self.chat_with_gpt(prompt)
                        index += 1
                        messages = f"{index}. {prompt}\n{response}"
                        await self.send_message(messages)
                        break
                    except Exception as e:
                        self.ap.logger.error(f"Error occurred while chatting with GPT: {e}")
                        await asyncio.sleep(5)

            # Send the scheduled message
            # TODO: 支持多人
            # await self.send_message(messages)

    async def send_message(self, messages: str):
        # Send the scheduled message
        await self.host.send_active_message(
            adapter=self.host.get_platform_adapters()[0],
            target_type=self.target_type,
            target_id=self.target_id,
            message=platform_types.MessageChain([platform_types.At(self.sender_id),
                platform_types.Plain(messages)
            ])
        )

    # 插件卸载时触发
    def __del__(self):
        self.ap.logger.info("SchedulerPlugin del")
        for key in self.data:
            if self.data[key].get("task") is not None:
                self.data[key]["task"].cancel()
        self.data.clear()
        self.client.close()
        self.client = None
