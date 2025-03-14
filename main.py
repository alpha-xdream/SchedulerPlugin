from pkg.plugin.context import register, handler, llm_func, BasePlugin, APIHost, EventContext
from pkg.plugin.events import *  # 导入事件类
from datetime import datetime, timedelta
import asyncio
import dateparser

# 注册插件
@register(name="Scheduler", description="自定义各种定时任务", version="0.1", author="AlphaXdream")
class SchedulerPlugin(BasePlugin):

    # 插件加载时触发
    def __init__(self, host: APIHost):
        pass

    # 异步初始化
    async def initialize(self):
        pass

    # 当收到个人消息时触发
    @handler(PersonNormalMessageReceived)
    async def person_normal_message_received(self, ctx: EventContext):
        msg = ctx.event.text_message  # 这里的 event 即为 PersonNormalMessageReceived 的对象
        if msg == "daily":

            # 输出调试信息
            self.ap.logger.debug("daily, classId:{}, {}".format(id(self), ctx.event.sender_id))

            target_info = {
            "target_id": str(ctx.event.launcher_id),
            "sender_id": str(ctx.event.sender_id), 
            "target_type": str(ctx.event.launcher_type).split(".")[-1].lower(),  # 获取枚举值的小写形式
            }
            self.target_id = target_info["target_id"]
            self.target_type = target_info["target_type"]
            self.sender_id = target_info["sender_id"]

            asyncio.create_task(self.schedule_daily_task("Daily Task Start 14:30!", "15:30"))
            asyncio.create_task(self.schedule_daily_task("Daily Task Start 14:45!", "15:45"))
            asyncio.create_task(self.schedule_daily_task("Daily Task Start 15:00!", "16:00"))
            # 回复消息 "hello, <发送者id>!"
            ctx.add_return("reply", ["已设置每日任务, {}!".format(ctx.event.sender_id)])

            # 阻止该事件默认行为（向接口获取回复）
            ctx.prevent_default()

    # 当收到群消息时触发
    @handler(GroupNormalMessageReceived)
    async def group_normal_message_received(self, ctx: EventContext):
        msg = ctx.event.text_message  # 这里的 event 即为 GroupNormalMessageReceived 的对象
        if msg == "hello":  # 如果消息为hello

            # 输出调试信息
            self.ap.logger.debug("hello, classId:{}, {}".format(id(self), ctx.event.sender_id))

            # 回复消息 "hello, everyone!"
            ctx.add_return("reply", ["hello, everyone!"])

            # 阻止该事件默认行为（向接口获取回复）
            ctx.prevent_default()

    async def runTask(self, messages: str, end_time: str, interval_minutes: int):
        start_time = datetime.now()
        
        end_time_parsed = dateparser.parse(end_time)
        if end_time_parsed is None:
            raise ValueError(f"Unable to parse the end time: {end_time}")
        end_time = end_time_parsed
        current_time = start_time
        result_messages = []  
        
        # 启动后台任务
        await self.replytask(messages, end_time, interval_minutes, current_time, result_messages)


    async def replytask(self, messages: str, end_time: str, interval_minutes: int, current_time: datetime, result_messages: list):
        # 每次检查时间，确保不超出end_time
        while current_time <= end_time:
            #print(f"Current time: {current_time}, End time: {end_time}")
            result_messages.append((current_time.strftime("%Y-%m-%d %H:%M:%S"), messages))
            #print(f"Scheduled message at {current_time.strftime('%Y-%m-%d %H:%M:%S')}: {messages}")
            
            await asyncio.sleep(interval_minutes * 60)

            current_time = datetime.now()

            if current_time > end_time:
                break

        await self.host.send_active_message(
                    adapter=self.host.get_platform_adapters()[0],
                    target_type=self.target_type,
                    target_id=self.target_id,
                    message=platform_types.MessageChain([platform_types.At(self.sender_id),
                        platform_types.Plain(messages)
                    ])
                )

    async def schedule_daily_task(self, messages: str, daily_time: str):
        """
        Schedule a task to send a message at a fixed daily time.

        :param messages: The message to be sent.
        :param daily_time: The time of day to send the message, in "HH:MM" format.
        """
        while True:
            now = datetime.now()
            # Parse the target time for today
            target_time = datetime.strptime(daily_time, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
            
            # If the target time has already passed today, schedule for the next day
            if now > target_time:
                target_time += timedelta(days=1)
            
            # Calculate the number of seconds to wait until the target time
            wait_seconds = (target_time - now).total_seconds()
            self.ap.logger.debug("schedule wait {}s, {}".format(wait_seconds, self.sender_id))
            await asyncio.sleep(wait_seconds)
            
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
        pass
