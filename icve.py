from urllib3.util.retry import Retry
from requests.packages import urllib3
from requests.adapters import HTTPAdapter
import time
import requests as rqs  # 首先安装依赖 完整安装python环境后 打开命令行输入: pip install requests
import random

sess = rqs.Session()

auth = ''  # 设置为自己的auth
# 谷歌(Chrome系浏览器): 浏览器上登录职教云后，
#  - 点击地址栏(显示网址的位置)左侧小锁
#  - 点击 [Cookie]
#  - 点击 [icve.com.cn]
#  - 点击 [Cookie]
#  - 点击 [auth]
#  - 双击下方内容右侧的一串字符串，全选,右键,复制
#  - 在本文件的第七行 [auth = ''] 的地方，将刚复制的内容粘贴在 [''] 之间

tastInterval = 1  # 课件上报间隔(秒)，太短会导致学习异常记录 (可能导致30分钟封禁)

videoIncrementInterval = 5  # 视频课件上报间隔(秒)，太短会导致学习异常记录 (可能导致30分钟封禁)

videoIncrementBase = 20  # 视频上报进度的基本值 大于20极有可能导致学习异常记录 (可能导致30分钟封禁)

# 视频上报进度的插值 随机数最大值 videoIncrementBase + videoIncrementX 不宜大于20 (可能导致30分钟封禁)
videoIncrementX = 3


def getCourseList():
    """
    获取学习的课程的列表

    Retures:
        [{courseOpenId,openClassId}]
    """
    return sess.get(
        "https://zjy2.icve.com.cn/api/student/learning/getLearnningCourseList").json()['courseList']


def getProcessList(courseOpenId, openClassId):
    """
    获取课件列表

    Retures:
        (moduleId, [{id}])
    """
    r = sess.post(
        "https://zjy2.icve.com.cn/api/study/process/getProcessList", data={
            "courseOpenId": (None, courseOpenId),
            "openClassId":  (None, openClassId)
        })
    json = r.json()
    return (json['progress']['moduleId'], json['progress']['moduleList'])


def getTopicByModuleId(courseOpenId, moduleId):
    """
    获取模块列表

    Retures:
        [{id, name}]
    """
    r = sess.post("https://zjy2.icve.com.cn/api/study/process/getTopicByModuleId", data={
        'courseOpenId': (None, courseOpenId),
        'moduleId': (None, moduleId)
    })
    return r.json()['topicList']


def getCellByTopicId(courseOpenId, openClassId, topicId):
    """
    获取模块里的任务列表

    Returns:
        [{cellName, Id, categoryName(
            子节点, 图片, 视频, ppt), courseOpenId, parentId, stuCellPercent, topicId, childNodeList}]
    """
    r = sess.post("https://zjy2.icve.com.cn/api/study/process/getCellByTopicId", data={
        'courseOpenId': (None, courseOpenId),
        'openClassId': (None, openClassId),
        'topicId': (None, topicId)
    })
    return r.json()['cellList']


def doneCellTask(cell, openClassId, moduleId):
    """
    完成模块里的单个任务，根据任务类型调用相应方法
    """
    cate = cell['categoryName']  # 任务类型 视频 文档 图片 ppt 子节点
    print("\n试图完成 {type} 类型任务: 【{name}】 ...".format(
        type=cate, name=cell['cellName']))
    retmsg = "Unknow"  # 请求返回的状态
    percent = 0  # 任务进度
    if 'stuCellPercent' in cell:
        percent = cell['stuCellPercent']
    elif 'stuCellFourPercent' in cell:
        percent = cell['stuCellFourPercent']
    if percent == 100:
        retmsg = "100%进度，任务跳过"
    if (percent != 100):
        if cate == "视频":
            retmsg = doneCellVideo(cell, openClassId, moduleId)
        elif cate == "图片":
            retmsg = doneCellImage(cell, openClassId, moduleId)
        elif cate == "ppt":
            retmsg = doneCellPPT(cell, openClassId, moduleId)
        elif cate == "文档":
            retmsg = doneCellDoc(cell, openClassId, moduleId)
        elif cate == "压缩包":
            retmsg = doneCellZip(cell, openClassId, moduleId)
        elif cate == "子节点":
            print("试图完成 {name} 的多个子任务...".format(
                type=cate, name=cell['cellName']))
            for cell in cell['childNodeList']:
                doneCellTask(cell, openClassId, moduleId)
            retmsg = "操作成功！"
    print("任务类型：【{type}】 结果: 【{retmsg}】 任务名称: 【{name}】 等待冷却时间".format(
        type=cate, name=cell['cellName'], retmsg=retmsg))
    if percent != 100:
        time.sleep(tastInterval)  # 等待5s 免得被ban了
    return None


def doneCellZip(cell, openClassId, moduleId):
    """
    完成压缩包类任务 这。。。点进去看一下就完成了，不需要真的下载下来 所以这里只用两个请求足矣 (未经过测试...)
    """
    vd = viewDirectory(
        cell['courseOpenId'],
        openClassId,
        cell['Id'],
        's',
        moduleId
    )
    return stuProcessCellLog(
        cell['courseOpenId'],
        openClassId,
        cell['Id'],
        vd['guIdToken'],
        0,
        cellLogId=vd['cellLogId']
    )['msg']


def doneCellDoc(cell, openClassId, moduleId):
    """
    完成文档任务 请求和ppt、图片一致...
    """
    return doneCellPPT(cell, openClassId, moduleId)


def doneCellVideo(cell, openClassId, moduleId):
    """
    完成视频观看任务
    """
    vd = viewDirectory(cell['courseOpenId'], openClassId,
                       cell['Id'], 's', moduleId)
    audioVideoLong = vd['audioVideoLong']  # 目标观看位置
    guIdToken = vd['guIdToken']
    studyNewlyTime = vd['stuStudyNewlyTime']  # 上次观看位置
    inc = studyNewlyTime  # inc下次上报的进度 初始化为已有进度
    linc = inc  # 上次上报的进度
    while(inc < audioVideoLong):
        inc += videoIncrementBase + random.random() * videoIncrementX  # 设置下次上报的进度
        if inc >= audioVideoLong:
            inc = audioVideoLong
        print("  > 等待冷却时间")
        time.sleep(videoIncrementInterval)  # 等待5s 免得被ban了
        m, s = divmod(audioVideoLong, 60)  # 总时长 分秒
        m2, s2 = divmod(inc, 60)  # 进度时长 分秒
        msg = stuProcessCellLog(cell['courseOpenId'],
                                openClassId, cell['Id'],
                                guIdToken, "{:.6f}".format(inc),
                                cellLogId=vd['cellLogId'])
        if '操作成功！' not in str(msg):
            return "试图提交进度到" + str(inc) + "时发生错误:" + str(msg['msg'])
        print(" 【{cellName}】 进度上报成功，当前完成度: {p:.2f}% 视频总时长: {sc} 当前进度时长: {ssc} 跳过{jump}".format(
            cellName=vd['cellName'],
            old=inc,
            max=audioVideoLong,
            p=(inc/audioVideoLong) * 100,
            sc="%02d分%02d秒" % (m, s),
            ssc="%02d分%02d秒" % (m2, s2),
            jump="%02d秒" % (inc - linc)
        ))
        linc = inc
    return "操作完成~"


def doneCellImage(cell, openClassId, moduleId):
    """
    完成图片查看任务，传参与ppt一样故直接返回doneCellPPT的数据
    """
    return doneCellPPT(cell, openClassId, moduleId)


def doneCellPPT(cell, openClassId, moduleId):
    """
    完成ppt查看任务
    """
    vd = viewDirectory(cell['courseOpenId'], openClassId,
                       cell['Id'], 's', moduleId)
    guIdToken = vd['guIdToken']
    studyNewlyTime = vd['stuStudyNewlyTime']
    studyNewlyPicNum = vd['pageCount']
    return stuProcessCellLog(cell['courseOpenId'], openClassId, cell['Id'], guIdToken,
                             studyNewlyTime, studyNewlyPicNum=studyNewlyPicNum, cellLogId=vd['cellLogId'], picNum=studyNewlyPicNum)['msg']


def stuProcessCellLog(courseOpenId, openClassId, cellId, token, studyNewlyTime, studyNewlyPicNum=0, cellLogId="", picNum=0):
    """
    调用接口查询课件进度，完成课件进度主要通过该接口
    """
    return sess.post("https://zjy2.icve.com.cn/api/common/Directory/stuProcessCellLog", data={
        'courseOpenId': (None, courseOpenId),
        'openClassId': (None, openClassId),
        'cellId': (None, cellId),
        'picNum': (None, picNum),
        'cellLogId': (None, cellLogId),
        'studyNewlyTime': (None, studyNewlyTime),
        'studyNewlyPicNum': (None, studyNewlyPicNum),
        'token': token,
    }).json()


def changeStuStudyProcessCellData(courseOpenId, openClassId, moduleId, cellId, cellName):
    r = sess.post("https://zjy2.icve.com.cn/api/common/Directory/changeStuStudyProcessCellData", data={
        'courseOpenId': (None, courseOpenId),
        'openClassId': (None, openClassId),
        'cellId': (None, cellId),
        'moduleId': (None, moduleId),
        'cellName': (None, cellName)
    })
    print(r.json())
    if r.json()['code'] != 1:
        raise Exception(
            "changeStuStudyProcessCellData 失败 {e}".format(e=r.text))
    return


def viewDirectory(courseOpenId, openClassId, cellId, flag, moduleId):
    """
    获取课件信息，主要用与获取guIdToken和视频的总时长、ppt的总页数

    Returns:
        {
            audioVideoLong(视频时长),
            courseOpenId,
            courseName,
            openClassId,
            moduleId,
            topicId,
            cellId,
            pageCount,
            cellLogId,
            downLoadUrl,
            guIdToken,
            stuCellViewTime(共观看时间),
            stuStudyNewlyPicCount,
            stuStudyNewlyTime(观看时间)
        }
    """
    r = sess.post("https://zjy2.icve.com.cn/api/common/Directory/viewDirectory", data={
        'courseOpenId': (None, courseOpenId),
        'openClassId': (None, openClassId),
        'cellId': (None, cellId),
        'flag': (None, flag),
        'moduleId': (None, moduleId)
    })
    json = r.json()
    if (json['code'] == -100):
        changeStuStudyProcessCellData(
            json['currCourseOpenId'],
            json['currOpenClassId'],
            json['currModuleId'],
            json['curCellId'],
            json['currCellName'])
        return viewDirectory(
            json['currCourseOpenId'],
            json['currOpenClassId'],
            json['curCellId'],
            flag,
            json['currModuleId']
        )
    elif '异常学习行为' in str(r.text):
        raise Exception(r.text)
    return r.json()

# DEFAULT CLI SHELL


def courseStudy(courseList):
    print("|=====课程列表=====|")
    for course in courseList:
        print("{idx}: {name}".format(idx=courseList.index(
            course), name=course["courseName"]))
    print("{idx}: {name}".format(
        idx=len(courseList), name="【退出】"))
    i = int(input("> 选择课程:(0-{max})".format(max=len(courseList))))
    if i == len(courseList):
        return False
    course = courseList[i]
    courseOpenId = course['courseOpenId']
    openClassId = course['openClassId']

    # 获取课程下的模块
    (currentProcessModuleId, processList) = getProcessList(
        courseOpenId, openClassId)

    while(processStudy(currentProcessModuleId, processList, courseOpenId, openClassId)):  # 进入模块学习循环
        pass
    return True


def processStudy(currentProcessModuleId, processList, courseOpenId, openClassId):
    print("|=====模块列表=====|")
    # 系统认为当前正在学习的模块位于0
    currentProcess = next(
        (x for x in processList if x['id'] == currentProcessModuleId), None)
    print('当前教学模块: \n0: 【{name}】'.format(
        name=currentProcess['name']))
    for pro in processList:
        print("{idx}: {name}".format(
            idx=processList.index(pro) + 1, name=pro['name']))
    print("{idx}: {name}".format(
        idx=len(processList) + 1, name="【刷完某模块所有内容(输入8后输入模块前的数字)】"))
    print("{idx}: {name}".format(
        idx=len(processList) + 2, name="【刷完所有模块所有内容】"))
    print("{idx}: {name}".format(
        idx=len(processList) + 3, name="【返回】"))
    i = int(input("> 选择模块:(0-{max})".format(max=len(processList)+3)))
    if i == 0:
        moduleId = currentProcessModuleId
    elif i == len(processList) + 1:
        ii = int(input("> 要刷完模块的数字:(0-{max})".format(max=len(processList))))
        moduleId = processList[ii-1]['id']
        topicList = getTopicByModuleId(courseOpenId, moduleId)
        topicStudy(topicList, courseOpenId, openClassId,
                   moduleId, directDone=True)
        return True  # TODO: 直接刷完该模块 选择模块
    elif i == len(processList) + 2:  # 刷完所有模块的内容
        for process in processList:
            moduleId = process['id']
            topicList = getTopicByModuleId(courseOpenId, moduleId)
            topicStudy(topicList, courseOpenId, openClassId,
                       moduleId, directDone=True)
        return True
    elif i == len(processList) + 3:
        return False  # 退出当前模块
    else:
        moduleId = processList[i-1]['id']

    topicList = getTopicByModuleId(courseOpenId, moduleId)
    while(topicStudy(topicList, courseOpenId, openClassId, moduleId)):  # 选择刷课循环
        pass
    return True


def topicStudy(topicList, courseOpenId, openClassId, moduleId, directDone=False):
    if directDone:  # 如果是直接完成所有模式
        for topic in topicList:
            cellList = getCellByTopicId(courseOpenId, openClassId, topic['id'])
            for cell in cellList:  # 对课件列表的课件逐个来完成进度
                doneCellTask(cell, openClassId, moduleId)
        return False

    print("|=====章节列表=====|")
    if len(topicList) == 0:
        print("无内容")
    for topic in topicList:
        print("{idx}: {name}".format(
            idx=topicList.index(topic), name=topic['name']))
    print("{idx}: {name}".format(
        idx=len(topicList), name="【返回】"))
    i = int(input("> 选择章节:(0-{max})".format(max=len(topicList))))
    if i == len(topicList):
        return False
    topic = topicList[i]
    cellList = getCellByTopicId(courseOpenId, openClassId, topic['id'])
    print('该章节共有{num}个课件:'.format(num=len(cellList)))
    for cell in cellList:
        percent = 0
        if 'stuCellPercent' in cell:
            percent = cell['stuCellPercent']
        elif 'stuCellFourPercent' in cell:
            percent = cell['stuCellFourPercent']
        print(
            " - {name} {percent}%".format(name=cell['cellName'], percent=percent))
    for cell in cellList:  # 对课件列表的课件逐个来完成进度
        doneCellTask(cell, openClassId, moduleId)
    return True


# 登录后的cookie
sess.cookies = rqs.sessions.cookiejar_from_dict({
    'auth': auth,
})


retry = Retry(connect=3, backoff_factor=0.5)
adapter = HTTPAdapter(max_retries=retry)
urllib3.disable_warnings(True)


def cliMain():
    global sess
    global auth
    sess.mount("https://", adapter)
    if len(auth) < 5:
        print("""# 谷歌(Chrome系浏览器): 浏览器上登录职教云后，
#  - 点击地址栏(显示网址的位置)左侧小锁
#  - 点击 [Cookie]
#  - 点击 [icve.com.cn]
#  - 点击 [Cookie]
#  - 点击 [auth]
#  - 双击下方内容右侧的一串字符串,全选,右键,复制
#  - 在本窗口右键，粘贴内容，回车""")
        auth = input("请输入auth:")
        sess.cookies = rqs.sessions.cookiejar_from_dict({
            'auth': auth
        })
        if len(auth) < 5:
            raise Exception("登录信息不能为空")
    print("获取课程列表...")
    courseList = getCourseList()  #
    while(courseStudy(courseList)):  # 进入课程学习循环
        pass


if __name__ == "__main__":
    cliMain()
