#!/usr/bin/env python

'''
Copyright 2012 the original author or authors.
See the NOTICE file distributed with this work for additional
information regarding copyright ownership.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
'''

import roslib
roslib.load_manifest('rospilot')
import rospy
import json
import cherrypy
import threading
import os
import socket
import glob
import std_srvs.srv
import rospilot.srv
import sensor_msgs.msg
import urllib2
import time
import pkg_resources
from optparse import OptionParser

STATIC_PATH = pkg_resources.resource_filename('rospilot.assets', '')

PORT_NUMBER = 8085


class API(object):
    def __init__(self, node):
        self.node = node

    @cherrypy.expose
    def media(self):
        paths = []
        with self.node.lock:
            paths = os.listdir(self.node.media_path)
        paths = ['/media/' + path for path in paths]
        objs = []
        for path in reversed(sorted(paths)):
            if path.endswith('jpg'):
                objs.append({"type": "image", "url": path})
            else:
                objs.append({"type": "video", "url": path})
        return json.dumps({'objs': objs})

    @cherrypy.expose
    def camera(self, action):
        url = 'http://localhost:8080/snapshot?topic=/camera/image_raw/compressed'
        resp = urllib2.urlopen(url)
        cherrypy.response.headers['Content-Type'] = resp.info()['Content-Type']
        return resp.read()


class Index(object):
    @cherrypy.expose
    def index(self):
        params = {'google_maps': '', 'gmaps': ''}
        try:
            socket.getaddrinfo('google.com', 'http')
            params['google_maps'] = '<script src="https://maps.googleapis.com/maps/api/js?v=3.exp&sensor=false"></script>'
            params['gmaps'] = '<script src="/static/gmaps.js"></script>'
        except:
            pass
        # TODO: this should probably be replaced with Jinja, or another
        # templating library
        template = open(os.path.join(STATIC_PATH, "index.html")).read()
        return template.format(**params)


class WebUiNode(object):
    def __init__(self, media_path):
        rospy.Subscriber('camera/image_raw/compressed',
                         sensor_msgs.msg.CompressedImage, self.handle_image)
        rospy.Service('take_picture',
                      std_srvs.srv.Empty,
                      self.take_picture)
        rospy.Service('glob',
                      rospilot.srv.Glob,
                      self.handle_glob)
        rospy.Service('shutdown',
                      std_srvs.srv.Empty,
                      self.handle_shutdown)
        self.lock = threading.Lock()
        self.last_image = None
        self.ptp_capture_image = rospy.ServiceProxy('camera/capture_image',
                                                    rospilot.srv.CaptureImage)
        self.media_path = os.path.expanduser(media_path)
        if not os.path.exists(self.media_path):
            os.makedirs(self.media_path)

        cherrypy.server.socket_port = PORT_NUMBER
        cherrypy.server.socket_host = '0.0.0.0'
        # No autoreloading
        cherrypy.engine.autoreload.unsubscribe()
        conf = {
            '/static': {'tools.staticdir.on': True,
                        'tools.staticdir.dir': STATIC_PATH
                        },
            '/media': {'tools.staticdir.on': True,
                       'tools.staticdir.dir': self.media_path
                       }
        }
        index = Index()
        index.api = API(self)
        cherrypy.tree.mount(index, config=conf)
        cherrypy.log.screen = False

    def handle_image(self, data):
        with self.lock:
            self.last_image = data

    def handle_glob(self, request):
        return rospilot.srv.GlobResponse(glob.glob(request.pattern))

    def handle_shutdown(self, request):
        os.system('shutdown now -P')
        return std_srvs.srv.EmptyResponse()

    def take_picture(self, request):
        if self.ptp_capture_image is not None:
            image = self.ptp_capture_image().image
        else:
            image = self.last_image

        with self.lock:
            next_id = int(round(time.time() * 1000))

            filename = "{0:05}.jpg".format(next_id)
            path = "{0}/{1}".format(self.media_path, filename)

            with open(path, 'w') as f:
                f.write(image.data)
        return std_srvs.srv.EmptyResponse()

    def run(self):
        rospy.init_node('rospilot_webui')
        rospy.loginfo("Web UI is running")
        cherrypy.engine.start()
        rospy.spin()
        cherrypy.engine.exit()

if __name__ == '__main__':
    parser = OptionParser("web_ui.py <options>")
    parser.add_option(
        "--media_path",
        dest="media_path",
        type='string',
        help="Directory to store media generated by drone",
        default="/tmp")
    (opts, args) = parser.parse_args()

    node = WebUiNode(media_path=opts.media_path)
    node.run()
