#!/usr/bin/python
##############################################################################
#
#    TERP: a Text-mode ERP Client
#    Copyright (C) 2010 by Almacom (Thailand) Ltd.
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from optparse import OptionParser
import curses
import curses.textpad
import sys
import time
import xmlrpclib
import xml.etree.ElementTree
import pdb
import traceback

parser=OptionParser()
parser.add_option("-H","--host",dest="host",help="host name",metavar="HOST",default="127.0.0.1")
parser.add_option("-P","--port",dest="port",help="port number",metavar="HOST",default=8069)
parser.add_option("-d","--db",dest="dbname",help="database",metavar="DB")
parser.add_option("-u","--uid",dest="uid",help="user ID",metavar="UID",default=1)
parser.add_option("-p","--passwd",dest="passwd",help="user password",metavar="PASSWD",default="admin")
parser.add_option("--debug",action="store_true",dest="debug",help="debug mode",default=False)
(opts,args)=parser.parse_args()

if opts.debug:
    def ex_info(type,value,tb):
        traceback.print_exception(type,value,tb)
        pdb.pm()
    sys.excepthook=ex_info

rpc=xmlrpclib.ServerProxy("http://%s:%d/xmlrpc/object"%(opts.host,opts.port))

dbname=opts.dbname
if not dbname:
    raise Exception("Missing dbname")
uid=opts.uid
passwd=opts.passwd

screen=None
root_panel=None
log_file=file("/tmp/terp.log","a")

def log(*args):
    if not log_file:
        return
    msg=" ".join([str(a) for a in args])
    log_file.write(msg+"\n")
    log_file.flush()

def rpc_exec(*args):
    try:
        return rpc.execute(dbname,uid,passwd,*args)
    except Exception,e:
        raise Exception("rpc_exec failed: %s %s %s %s\n%s"%(dbname,uid,passwd,str(args),str(e)))

def rpc_exec_wkf(*args):
    try:
        return rpc.exec_workflow(dbname,uid,passwd,*args)
    except Exception,e:
        raise Exception("rpc_exec_wkf failed: %s %s %s %s\n%s"%(dbname,uid,passwd,str(args),str(e)))

def set_trace():
    curses.nocbreak()
    screen.keypad(0)
    curses.echo()
    curses.endwin()
    pdb.set_trace()

class Widget(object):
    def on_unfocus(self,arg,source):
        pass

    def __init__(self):
        self.x=None
        self.y=None
        self.w=None
        self.h=None
        self.maxw=None
        self.maxh=None
        self.borders=[0,0,0,0]
        self.padding=[0,0,0,0]
        self.valign="top"
        self.halign="left"
        self.cx=None
        self.cy=None
        self.can_focus=False
        self.has_focus=False
        self.states_f={}
        self.view_attrs={}
        self.states_v=None
        self.attrs_v={}
        self.colspan=1
        self.rowspan=1
        self.parent=None
        self.window=None
        self.win_x=None
        self.win_y=None
        self.listeners={
            "keypress": [],
            "unfocus": [],
        }
        self.add_event_listener("unfocus",self.on_unfocus)
        self.record=None
        self.field=None
        self.invisible=False
        self.editable=True

    def to_s(self,d=0):
        s="  "*d
        s+=" "+self.__class__.__name__
        for name in dir(self):
            if name.startswith("_"):
                continue
            if not name in ("x","y","maxw","maxh","h","w","can_focus","has_focus","borders","padding","seps"):
                continue
            val=getattr(self,name)
            if callable(val):
                continue
            s+=" %s=%s"%(name,str(val))
        for name,val in self.view_attrs.items():
            s+=" %s=%s"%(name,str(val))
        return s

    def draw(self):
        raise Exception("method not implemented")

    def refresh(self):
        pass

    def get_tabindex(self):
        if self.can_focus:
            return [self]
        else:
            return []

    def add_event_listener(self,type,listener):
        self.listeners[type].append(listener)

    def process_event(self,type,param,source):
        if self!=source:
            return False
        for listener in self.listeners[type]:
            listener(param,source)
        return True

    def clear_focus(self):
        if self.has_focus:
            self.has_focus=False
            self.process_event("unfocus",None,self)

    def set_focus(self):
        self.has_focus=self.can_focus
        if self.has_focus:
            return self
        return None

    def get_focus(self):
        return self.has_focus and self or None

    def set_cursor(self):
        screen.move(self.win_y+self.y,self.win_x+self.x)

    def update_attrs(self):
        self.string="Undefined"
        self.colspan=1
        self.col=4
        self.readonly=not self.editable
        self.invisible=False
        self.domain=[]
        self.context={}
        if self.field:
            if "string" in self.field:
                self.string=self.field["string"]
            if not self.readonly and "readonly" in self.field:
                self.readonly=self.field["readonly"]
            if "domain" in self.field:
                self.domain=self.field["domain"]
        if "string" in self.view_attrs:
            self.string=self.view_attrs["string"]
        if "colspan" in self.view_attrs:
            self.colspan=int(self.view_attrs["colspan"])
        if "col" in self.view_attrs:
            self.col=int(self.view_attrs["col"])
        if not self.readonly and "readonly" in self.view_attrs:
            self.readonly=self.eval_expr(self.view_attrs["readonly"])
        if "invisible" in self.view_attrs:
            self.invisible=self.eval_expr(self.view_attrs["invisible"])
        if "domain" in self.view_attrs:
            self.domain+=self.eval_expr(self.view_attrs["domain"])
        if "context" in self.view_attrs:
            self.context=self.eval_expr(self.view_attrs["context"])

    def record_changed(self,record,field=None):
        if record==self.record and not field:
            self.update_attrs()

    def eval_expr(self,expr):
        class Env(dict):
            def __init__(self,wg):
                self.wg=wg
            def __getitem__(self,name):
                if not self.wg.record:
                    return None
                return self.wg.record.get_val(name)
        return eval(expr,Env(self))

class Panel(Widget):
    def __init__(self):
        super(Panel,self).__init__()
        self._childs=[]

    def add(self,wg):
        wg.parent=self
        self._childs.append(wg)

    def to_s(self,d=0):
        s=super(Panel,self).to_s(d)
        for c in self._childs:
            s+="\n"+c.to_s(d+1)
        return s

    def _vis_childs(self):
        for c in self._childs:
            if c.invisible:
                continue
            yield c

    def compute(self,h,w,y,x):
        self._compute_pass1()
        self.h=h
        self.w=w
        self.y=y
        self.x=x
        self._compute_pass2()

    def draw(self):
        for c in self._vis_childs():
            c.draw()

    def refresh(self):
        for c in self._vis_childs():
            c.refresh()

    def process_event(self,type,param,source):
        processed=False
        for wg in self._childs:
            if wg.process_event(type,param,source):
                processed=True
                break
        if not processed and self!=source:
            return False
        for listener in self.listeners[type]:
            listener(param,source)
        return True

    def get_tabindex(self):
        ind=super(Panel,self).get_tabindex()
        for wg in self._vis_childs():
            ind+=wg.get_tabindex()
        return ind

    def clear_focus(self):
        super(Panel,self).clear_focus()
        for wg in self._childs:
            wg.clear_focus()

    def set_focus(self):
        res=super(Panel,self).set_focus()
        if res:
            return res
        for wg in self._childs:
            res=wg.set_focus()
            if res:
                return res

    def get_focus(self):
        wg_f=super(Panel,self).get_focus()
        if wg_f:
            return wg_f
        for wg in self._childs:
            wg_f=wg.get_focus()
            if wg_f:
                return wg_f
        return None

class ScrollPanel(Panel):
    def __init__(self):
        super(ScrollPanel,self).__init__()
        self.y0=0

    def _compute_pass1(self):
        if self._childs:
            wg=self._childs[0]
            wg._compute_pass1()
        else:
            wg=None
        if self.maxw is None:
            self.maxw=wg and wg.maxw or 1
            if self.maxw!=-1:
                self.maxw+=self.borders[1]+self.borders[3]+1
        if self.maxh is None:
            self.maxh=wg and wg.maxh or 1
            if self.maxh!=-1:
                self.maxh+=self.borders[0]+self.borders[2]

    def _compute_pass2(self):
        w=self.w-self.borders[1]-self.borders[3]-1
        h=self.h-self.borders[0]-self.borders[2]
        for wg in self._childs:
            wg.y=0
            wg.x=0
            wg.w=w
            wg.h=h
            wg.window=curses.newpad(wg.h+10,wg.w+10) #XXX
            wg.win_y=self.win_y+self.y+self.borders[0]
            wg.win_x=self.win_x+self.x+self.borders[3]
            wg._compute_pass2()

    def draw(self):
        win=self.window
        for wg in self._childs:
            wg.window.clear()
            wg.draw()
        if self.borders[0]:
            curses.textpad.rectangle(win,self.y,self.x,self.y+self.h-1,self.x+self.w-1)
        win.vline(self.y,self.x+self.w-1,curses.ACS_VLINE,self.h)
        win.vline(self.y,self.x+self.w-1,curses.ACS_CKBOARD,3)

    def refresh(self):
        wg=self._childs[0]
        wg.window.refresh(self.y0,0,self.y+self.borders[0],self.x+self.borders[3],self.y+self.h-1-self.borders[2],self.x+self.w-1-self.borders[1]-1)
        wg.refresh()

class DeckPanel(Panel):
    def _vis_childs(self):
        if self.cur_wg:
            yield self.cur_wg

    def on_keypress(self,k,source):
        if k==curses.KEY_RIGHT:
            if source==self:
                chs=[wg for wg in self._vis_childs()]
                i=chs.index(self.cur_wg)
                i=(i+1)%len(chs)
                self.cur_wg=chs[i]
                root_panel.compute()
                root_panel.draw()
                root_panel.refresh()
                root_panel.set_cursor()
        elif k==curses.KEY_LEFT:
            if source==self:
                chs=[wg for wg in self._vis_childs()]
                i=chs.index(self.cur_wg)
                i=(i-1)%len(chs)
                self.cur_wg=chs[i]
                root_panel.compute()
                root_panel.draw()
                root_panel.refresh()
                root_panel.set_cursor()

    def __init__(self):
        super(DeckPanel,self).__init__()
        self.cur_wg=None
        self.add_event_listener("keypress",self.on_keypress)

    def add(self,wg):
        super(DeckPanel,self).add(wg)
        if self.cur_wg==None:
            self.cur_wg=wg

    def set_cur_wg(self,wg):
        self.cur_wg=wg

    def remove(self,wg):
        i=self._childs.index(wg)
        self._childs.pop(i)
        if wg==self.cur_wg:
            if self._childs:
                self.cur_wg=self._childs[i%len(self._childs)]
            else:
                self.cur_wg=None

    def _compute_pass1(self):
        if not self._childs:
            return
        for wg in self._vis_childs():
            if hasattr(wg,"_compute_pass1"):
                wg._compute_pass1()
        if self.maxw is None:
            maxws=[wg.maxw for wg in self._vis_childs()]
            if -1 in maxws:
                self.maxw=-1
            else:
                self.maxw=max(maxws)+self.borders[1]+self.borders[3]+self.padding[1]+self.padding[3]
        if self.maxh is None:
            maxhs=[wg.maxh for wg in self._vis_childs()]
            if -1 in maxhs:
                self.maxh=-1
            else:
                self.maxh=max(maxhs)+self.borders[0]+self.borders[2]+self.padding[0]+self.padding[2]

    def _compute_pass2(self):
        w=self.w-self.borders[1]-self.borders[3]-self.padding[1]-self.padding[3]
        h=self.h-self.borders[0]-self.borders[2]-self.padding[0]-self.padding[2]
        for wg in self._vis_childs():
            if wg.maxw==-1:
                wg.w=w
            else:
                wg.w=min(w,wg.maxw)
            if wg.maxh==-1:
                wg.h=h
            else:
                wg.h=min(h,wg.maxh)
            wg.y=self.y+self.borders[0]+self.padding[0]
            wg.x=self.x+self.borders[3]+self.padding[3]
            wg.window=self.window
            wg.win_y=self.win_y
            wg.win_x=self.win_x
        for wg in self._vis_childs():
            if hasattr(wg,"_compute_pass2"):
                wg._compute_pass2()

    def draw(self):
        win=self.window
        if self.borders[0]:
            curses.textpad.rectangle(win,self.y,self.x,self.y+self.h-1,self.x+self.w-1)
        if self.cur_wg:
            self.cur_wg.draw()

    def refresh(self):
        if self.cur_wg:
            self.cur_wg.refresh()

    def set_focus(self):
        wg_f=Widget.set_focus(self)
        if wg_f:
            return wg_f
        if not self.cur_wg:
            return None
        return self.cur_wg.set_focus()

    def get_tabindex(self):
        ind=Widget.get_tabindex(self)
        if self.cur_wg:
            ind+=self.cur_wg.get_tabindex()
        return ind

class TabPanel(DeckPanel):
    def __init__(self):
        super(TabPanel,self).__init__()
        self.padding=[1,0,0,0]
        self.can_focus=True
        def on_keypress(k,source):
            if k==ord('c'):
                if source==self:
                    self.remove(self.cur_wg)
                    root_panel.draw()
                    root_panel.set_cursor()
        self.add_event_listener("keypress",on_keypress)

    def compute_tabs(self):
        x=self.x
        self.tab_x=[]
        for wg in self._childs:
            self.tab_x.append(x)
            x+=len(wg.name)+3

    def _compute_pass2(self):
        super(TabPanel,self)._compute_pass2()
        self.compute_tabs()

    def draw(self):
        win=self.window
        i=0
        for wg in self._childs:
            x=self.tab_x[i]
            s="%d %s "%(i+1,wg.name)
            if wg==self.cur_wg:
                win.addstr(self.y,x,s,curses.A_REVERSE)
            else:
                win.addstr(self.y,x,s)
            i+=1
        super(TabPanel,self).draw()

    def set_cursor(self):
        if not self.cur_wg:
            return
        i=self._childs.index(self.cur_wg)
        x=self.tab_x[i]
        screen.move(self.win_y+self.y,self.win_x+x)

class Notebook(DeckPanel):
    def __init__(self):
        super(Notebook,self).__init__()
        self.can_focus=True
        self.tab_x=[]
        self.borders=[1,1,1,1]

    def compute_tabs(self):
        x=self.x+3
        self.tab_x=[]
        for wg in self._vis_childs():
            self.tab_x.append(x)
            x+=len(wg.string)+3

    def _compute_pass2(self):
        super(Notebook,self)._compute_pass2()
        self.compute_tabs()

    def draw(self):
        win=self.window
        super(Notebook,self).draw()
        i=0
        for wg in self._vis_childs():
            x=self.tab_x[i]
            if x+len(wg.string)+1>=80:
                continue
            if i==0:
                win.addch(self.y,x-2,curses.ACS_RTEE)
            else:
                win.addch(self.y,x-2,curses.ACS_VLINE)
            s=" "+wg.string+" "
            if self.cur_wg==wg:
                win.addstr(self.y,x-1,s,curses.A_BOLD)
            else:
                win.addstr(self.y,x-1,s)
            if i==len(self._childs)-1:
                win.addch(self.y,x+len(wg.string)+1,curses.ACS_LTEE)
            i+=1

    def set_cursor(self):
        if not self.cur_wg:
            return
        chs=[wg for wg in self._vis_childs()]
        i=chs.index(self.cur_wg)
        x=self.tab_x[i]
        screen.move(self.win_y+self.y,self.win_x+x)

class Table(Panel):
    def __init__(self):
        super(Table,self).__init__()
        self.col=0
        self._childs=[]
        self.num_rows=0
        self.seps=[[(0,False)],[(0,False)]]
        self.h_top=None
        self.w_left=None
        self._next_cx=0
        self._next_cy=0

    def add(self,wg):
        if not wg.colspan or wg.colspan>self.col:
            raise Exception("invalid colspan")
        if self._next_cx+wg.colspan>self.col:
            self._next_cy+=1
            self._next_cx=0
        wg.cy=self._next_cy
        wg.cx=self._next_cx
        wg.parent=self
        self._childs.append(wg)
        self._next_cx+=wg.colspan
        self.num_rows=wg.cy+1

    def insert_row(self,cy,row):
        cx=0
        for wg in row:
            wg.cy=cy
            wg.cx=cx
            cx+=wg.colspan
            if cx>self.col:
                raise Exception("line too big")
        pos=None
        i=0
        for wg in self._childs:
            if wg.cy>=cy:
                if pos==None:
                    pos=i
                wg.cy+=1
            i+=1
        if pos==None:
            pos=len(self._childs)
        self._childs=self._childs[:pos]+row+self._childs[pos:]
        self.num_rows+=1

    def delete_row(self,cy):
        self._childs=[wg for wg in self._childs if wg.cy!=cy]
        for wg in self._childs:
            if wg.cy>cy:
                wg.cy-=1

    def newline(self):
        self._next_cy+=1
        self._next_cx=0

    def _get_sep_size(self,type,i):
        if type=="y":
            seps=self.seps[0]
        elif type=="x":
            seps=self.seps[1]
        else:
            raise Exception("invalid separator type")
        if i==0:
            return 0
        elif i-1<len(seps):
            return seps[i-1][0]
        else:
            return seps[-1][0]

    def _get_sep_style(self,type,i):
        if type=="y":
            seps=self.seps[0]
        elif type=="x":
            seps=self.seps[1]
        else:
            raise Exception("invalid separator type")
        if i==0:
            return False
        elif i-1<len(seps):
            return seps[i-1][1]
        else:
            return seps[-1][1]

    def _total_sep_size(self,type):
        if type=="y":
            n=self.num_rows
        elif type=="x":
            n=self.col
        else:
            raise Exception("invalid separator type")
        return sum([self._get_sep_size(type,i) for i in range(n)])

    def _compute_pass1(self):
        for widget in self._vis_childs():
            if hasattr(widget,"_compute_pass1"):
                widget._compute_pass1()
        # 1. compute container max width
        if self.maxw is None:
            expand=False
            for wg in self._vis_childs():
                if wg.maxw==-1:
                    expand=True
                    break
            if expand:
                self.maxw=-1
            else:
                w_left=[0]
                for i in range(1,self.col+1):
                    w_max=w_left[i-1]
                    for wg in self._vis_childs():
                        cr=wg.cx+wg.colspan
                        if cr!=i:
                            continue
                        w=w_left[wg.cx]+self._get_sep_size("x",wg.cx)+wg.maxw
                        if w>w_max:
                            w_max=w
                    w_left.append(w_max)
                self.maxw=self.borders[3]+self.borders[1]+w_left[-1]
        # 2. compute container max height
        if self.maxh is None:
            expand=False
            for wg in self._vis_childs():
                if wg.maxh==-1:
                    expand=True
                    break
            if expand:
                self.maxh=-1
            else:
                h_top=[0]
                for i in range(1,self.num_rows+1):
                    h_max=h_top[i-1]
                    for wg in self._vis_childs():
                        cr=wg.cy+wg.rowspan
                        if cr!=i:
                            continue
                        h=h_top[wg.cy]+self._get_sep_size("y",wg.cy)+wg.maxh
                        if h>h_max:
                            h_max=h
                    h_top.append(h_max)
                self.maxh=self.borders[2]+self.borders[0]+h_top[-1]

    def _compute_pass2(self):
        if not self._childs:
            self.w=0
            return
        # 1. compute child widths
        w_avail=self.w-self.borders[3]-self.borders[1]
        for wg in self._vis_childs():
            wg.w=0
        w_left=[0]*(self.col+1)
        w_rest=w_avail
        # allocate space fairly to every child
        while w_rest>0:
            w_alloc=w_rest-self._total_sep_size("x")
            if w_alloc>self.col:
                dw=w_alloc/self.col
            else:
                dw=1
            incr=False
            for wg in self._vis_childs():
                if wg.maxw!=-1:
                    if not wg.w<wg.maxw:
                        continue
                    dw_=min(dw,wg.maxw-wg.w)
                else:
                    dw_=dw
                wg.w+=dw_
                incr=True
                w=w_left[wg.cx]+self._get_sep_size("x",wg.cx)+wg.w
                cr=wg.cx+wg.colspan
                if w>w_left[cr]:
                    dwl=w-w_left[cr]
                    for i in range(cr,self.col+1):
                        w_left[i]+=dwl
                    w_rest=w_avail-w_left[-1]
                    if w_rest==0:
                        break
            if not incr:
                break
        self.w_left=w_left
        # add extra cell space to regions
        for wg in self._vis_childs():
            if wg.maxw!=-1 and wg.w==wg.maxw:
                continue
            w=w_left[wg.cx]+self._get_sep_size("x",wg.cx)+wg.w
            cr=wg.cx+wg.colspan
            if w<w_left[cr]:
                dw=w_left[cr]-w
                if wg.maxw!=-1:
                    dw=min(dw,wg.maxw-wg.w)
                wg.w+=dw
        # 2. compute child heights
        h_avail=self.h-self.borders[2]-self.borders[0]
        for wg in self._vis_childs():
            wg.h=0
        h_top=[0]*(self.num_rows+1)
        h_rest=h_avail
        # allocate space fairly to every child
        while h_rest>0:
            h_alloc=h_rest-self._total_sep_size("y")
            if h_alloc>self.num_rows:
                dh=h_alloc/self.num_rows
            else:
                dh=1
            incr=False
            for wg in self._vis_childs():
                if wg.maxh!=-1:
                    if not wg.h<wg.maxh:
                        continue
                    dh_=min(dh,wg.maxh-wg.h)
                else:
                    dh_=dh
                wg.h+=dh_
                incr=True
                h=h_top[wg.cy]+self._get_sep_size("y",wg.cy)+wg.h
                cr=wg.cy+wg.rowspan
                if h>h_top[cr]:
                    dht=h-h_top[cr]
                    for i in range(cr,self.num_rows+1):
                        h_top[i]+=dht
                    h_rest=h_avail-h_top[-1]
                    if h_rest==0:
                        break
            if not incr:
                break
        self.h_top=h_top
        # add extra cell space to regions
        for wg in self._vis_childs():
            if wg.maxh!=-1 and wg.h==wg.maxh:
                continue
            h=h_top[wg.cy]+self._get_sep_size("y",wg.cy)+wg.h
            cr=wg.cy+wg.rowspan
            if h<h_top[cr]:
                dh=h_top[cr]-h
                if wg.maxh!=-1:
                    dh=min(dh,wg.maxh-wg.h)
                wg.h+=dh
        # 3. compute child positions
        for wg in self._vis_childs():
            if wg.valign=="top":
                wg.y=self.y+self.borders[0]+self.h_top[wg.cy]+self._get_sep_size("y",wg.cy)
            elif wg.valign=="bottom":
                wg.y=self.y+self.borders[0]+self.h_top[wg.cy+wg.rowspan]-wg.h
            else:
                raise Exception("invalid valign: %s"%wg.valign)
            if wg.halign=="left":
                wg.x=self.x+self.borders[3]+w_left[wg.cx]+self._get_sep_size("x",wg.cx)
            elif wg.halign=="right":
                wg.x=self.x+self.borders[3]+w_left[wg.cx+wg.colspan]-wg.w
            else:
                raise Exception("invalid halign: %s"%wg.valign)
            wg.window=self.window
            wg.win_y=self.win_y
            wg.win_x=self.win_x
        for child in self._vis_childs():
            if hasattr(child,"_compute_pass2"):
                child._compute_pass2()

    def draw(self):
        win=self.window
        # draw borders
        if self.borders[0]:
            curses.textpad.rectangle(win,self.y,self.x,self.y+self.h-1,self.x+self.w-1)
        # draw vertical separators
        x0=self.x+self.borders[3]
        y0=self.y+self.borders[0]-1
        y1=self.y+self.h-self.borders[2]
        for i in range(1,self.col):
            if self._get_sep_style("x",i):
                x=x0+self.w_left[i]
                win.vline(y0+1,x,curses.ACS_VLINE,y1-y0-1)
                win.addch(y0,x,curses.ACS_TTEE)
                win.addch(y1,x,curses.ACS_BTEE)
        # draw horizontal separators
        y0=self.y+self.borders[0]
        x0=self.x+self.borders[3]-1
        x1=self.x+self.w-self.borders[1]
        for i in range(1,self.num_rows):
            if self._get_sep_style("y",i):
                y=y0+self.h_top[i]
                win.hline(y,x0+1,curses.ACS_HLINE,x1-x0-1)
                win.addch(y,x0,curses.ACS_LTEE)
                win.addch(y,x1,curses.ACS_RTEE)
                for j in range(1,self.col):
                    if self._get_sep_style("x",j):
                        x=x0+self.w_left[j]
                        win.addch(y,x+1,curses.ACS_PLUS)
        # draw cell contents
        super(Table,self).draw()

class Form(Table):
    def __init__(self):
        super(Form,self).__init__()
        self.relation=None
        self.maxw=-1
        self.seps=[[(0,False)],[(1,False)]]
        self.col=4
        self.context={}

class Group(Table):
    def __init__(self):
        super(Group,self).__init__()
        self.col=4
        self.seps=[[(0,False)],[(1,False)]]

class Page(Table):
    def __init__(self):
        super(Page,self).__init__()
        self.col=4
        self.seps=[[(0,False)],[(1,False)]]

class HorizontalPanel(Table):
    def __init__(self):
        super(HorizontalPanel,self).__init__()
        self.seps=[[(0,False)],[(1,True)]]

    def add(self,wg):
        wg.colspan=1
        self.col+=1
        super(HorizontalPanel,self).add(wg)

class VerticalPanel(Table):
    def __init__(self):
        super(VerticalPanel,self).__init__()
        self.seps=[[(0,False)],[(0,True)]]
        self.col=1

    def add(self,wg):
        wg.colspan=1
        super(VerticalPanel,self).add(wg)

class ListView(Table):
    def on_select(self,line_no):
        self.selected=[line_no]
        self.process_event("select",line_no,self)

    def on_keypress(self,k,source):
        if k==ord("\n"):
            if source in self._childs:
                i=self._childs.index(source)
                line_no=i/self.col
                if self.has_header:
                    line_no-=1
                self.on_select(line_no)

    def __init__(self):
        super(ListView,self).__init__()
        self.relation=None
        self.seps=[[(0,False)],[(1,True)]]
        self.selected=[]
        self.lines=[]
        self.num_lines=0
        self.has_header=False
        self.names=None
        self.listeners.update({
            "select": [],
        })
        self.add_event_listener("keypress",self.on_keypress)

    def make_header(self,headers):
        for header in headers:
            wg=Label()
            wg.string=header
            self.add(wg)
        self.has_header=True

    def make_line(self,vals):
        line=[]
        for i in range(self.col):
            wg=Label()
            wg.string=vals[self.names[i]]
            if i==0:
                wg.can_focus=True
            line.append(wg)
        return line

    def add_line(self,vals):
        self.lines.append(vals)
        self.num_lines+=1
        line=self.make_line(vals)
        for wg in line:
            self.add(wg)

    def add_lines(self,lines):
        for vals in lines:
            self.add_line(vals)

    def insert_line(self,line_no,vals):
        self.lines.insert(line_no,vals)
        self.num_lines+=1
        vals_=dict([(k,v) for k,v in vals.items() if k not in ("_depth","_open")]) # XXX
        line=self.make_line(vals_)
        row_no=line_no+(self.has_header and 1 or 0)
        self.insert_row(row_no,line)

    def insert_lines(self,line_no,lines):
        i=line_no
        for line in lines:
            self.insert_line(i,line)
            i+=1

    def delete_line(self,line_no):
        self.lines.pop(line_no)
        self.num_lines-=1
        row_no=line_no+(self.has_header and 1 or 0)
        self.delete_row(row_no)

    def delete_lines(self,line_no=None,num=None):
        if line_no==None:
            line_no=0
            num=self.num_lines
        elif num==None:
            num=1
        for i in range(num):
            self.delete_line(line_no)

    def set_cursor(self):
        screen.move(self.win_y+self.y+self.borders[0]+(self.has_header and 1+self.seps[0][0][0] or 0),self.win_x+self.x+self.borders[3])

    def draw(self):
        win=self.window
        super(ListView,self).draw()
        x=self.x+self.borders[3]
        w=self.w-self.borders[1]-self.borders[3]
        for sel in self.selected:
            wg=self._childs[sel*self.col]
            y=wg.y
            win.chgat(y,x,w,curses.A_BOLD)

    def set_lines(self,lines):
        self.delete_lines()
        self.add_lines(lines)

class TreeView(ListView):
    def on_keypress(self,k,source):
        if k==curses.KEY_RIGHT:
            if source in self._childs:
                i=self._childs.index(source)
                row_no=i/self.col
                line_no=row_no-(self.has_header and 1 or 0)
                line=self.lines[line_no]
                item=self.items[line["id"]]
                if not line["_open"] and item[self.parent.view["field_parent"]]:
                    self.process_event("open",item,self)
                    items=[self.items[id] for id in item[self.parent.view["field_parent"]]]
                    self.open_line(line_no,items)
                    root_panel.compute()
                    root_panel.draw()
                    root_panel.refresh()
                    root_panel.set_cursor()
        elif k==curses.KEY_LEFT:
            if source in self._childs:
                i=self._childs.index(source)
                row_no=i/self.col
                line_no=row_no-(self.has_header and 1 or 0)
                line=self.lines[line_no]
                item=self.items[line["id"]]
                if line["_open"]:
                    d=self.lines[line_no]["_depth"]
                    i=line_no+1
                    while i<len(self.lines) and self.lines[i]["_depth"]>d:
                        i+=1
                    self.delete_lines(line_no+1,i-(line_no+1))
                    line["_open"]=False
                    root_panel.compute()
                    root_panel.draw()
                    root_panel.refresh()
                    root_panel.set_cursor()
        elif k==ord("\n"):
            if source in self._childs:
                i=self._childs.index(source)
                row_no=i/self.col
                line_no=row_no-(self.has_header and 1 or 0)
                self.process_event("select",line_no,self)

    def __init__(self):
        super(TreeView,self).__init__()
        self.items={}
        self.listeners.update({
            "open": [],
        })

    def open_line(self,line_no,items):
        if line_no==None:
            d=0
        else:
            d=self.lines[line_no]["_depth"]+1
        lines=[]
        for item in items:
            line=item.copy()
            line["_depth"]=d
            line["_open"]=False
            line["name"]="  "*d+(item[self.parent.view["field_parent"]] and "/" or "")+item["name"]
            lines.append(line)
        super(TreeView,self).insert_lines(line_no!=None and line_no+1 or 0,lines)
        if line_no!=None:
            self.lines[line_no]["_open"]=True

    def add_items(self,items):
        for item in items:
            self.items[item["id"]]=item
        if not self.num_lines:
            self.open_line(None,items)

    def delete_items(self):
        self.items={}
        self.delete_lines()

class Label(Widget):
    def __init__(self):
        super(Label,self).__init__()
        self.maxh=1

    def _compute_pass1(self):
        self.maxw=len(self.string)

    def draw(self):
        win=self.window
        s=self.string[:self.w]
        win.addstr(self.y,self.x,s)

class Separator(Widget):
    def __init__(self):
        super(Separator,self).__init__()
        self.maxh=1
        self.maxw=-1

    def draw(self):
        win=self.window
        s="_"
        if self.string:
            s+=self.string[:self.w-1]
        s+="_"*(self.w-len(s))
        win.addstr(self.y,self.x,s)

class Button(Widget):
    def on_keypress(self,k,source):
        if source==self and k==ord("\n"):
            self.process_event("push",None,self)

    def on_push(self,arg,source):
        pass

    def __init__(self):
        super(Button,self).__init__()
        self.can_focus=True
        self.maxh=1
        self.listeners["push"]=[]
        self.add_event_listener("keypress",self.on_keypress)
        self.add_event_listener("push",self.on_push)

    def _compute_pass1(self):
        self.maxw=len(self.string)+2

    def draw(self):
        win=self.window
        s="["+self.string[:self.w-2]+"]"
        win.addstr(self.y,self.x,s)

    def set_cursor(self):
        screen.move(self.win_y+self.y,self.win_x+self.x+1)

class FormButton(Button):
    def on_push(self,arg,source):
        type=getattr(self,"type","wizard")
        if type=="wizard":
            rpc_exec_wkf(form.model,self.name,self.view_wg.obj_id)
            self.view_wg.read()
            root_panel.clear_focus()
            root_panel.set_focus()
            root_panel.set_cursor()
        else:
            raise Exception("invalid button type: %s"%type)

class FieldLabel(Widget):
    def __init__(self):
        super(FieldLabel,self).__init__()
        self.halign="right"
        self.maxh=1

    def _compute_pass1(self):
        self.maxw=len(self.string)+1

    def draw(self):
        win=self.window
        s=self.string[:self.w-1]
        s+=":"
        win.addstr(self.y,self.x,s)

class Input(Widget):
    def __init__(self):
        super(Input,self).__init__()
        self.name=None
        self.under=True
        self.domain=None
        self.context=None
        self.field=None

    def get_val(self):
        return self.record.get_val(self.name)

    def set_val(self,val):
        self.record.set_val(self.name,val)

    def on_change(self):
        pass

    def record_changed(self,record,field=None):
        super(Input,self).record_changed(record,field)
        if record==self.record and field==self.name:
            self.on_change()

class StringInput(Input):
    def on_keypress(self,k,source):
        if curses.ascii.isprint(k):
            new_str=self.str_val[:self.cur_pos]+chr(k)+self.str_val[self.cur_pos:]
            if self.is_valid(new_str):
                self.str_val=new_str
                self.cur_pos+=1
                if self.cur_pos-self.cur_origin>self.w-1:
                    self.cur_origin=self.cur_pos-self.w+1
                self.process_event("edit",new_str,self)
        elif k==curses.KEY_LEFT:
            self.cur_pos=max(self.cur_pos-1,0)
            if self.cur_pos<self.cur_origin:
                self.cur_origin=self.cur_pos
                self.draw()
            self.set_cursor()
        elif k==curses.KEY_RIGHT:
            self.cur_pos=min(self.cur_pos+1,len(self.str_val))
            if self.cur_pos-self.cur_origin>self.w-1:
                self.cur_origin=self.cur_pos-self.w+1
                self.draw()
            self.set_cursor()
        elif k==263:
            if self.cur_pos>=1:
                new_str=self.str_val[:self.cur_pos-1]+self.str_val[self.cur_pos:]
                if self.is_valid(new_str):
                    self.str_val=new_str
                    self.cur_pos-=1
                    if self.cur_pos<self.cur_origin:
                        self.cur_origin=self.cur_pos
                    self.process_event("edit",new_str,self)
        elif k==330:
            if self.cur_pos<=len(self.str_val)-1:
                new_str=self.str_val[:self.cur_pos]+self.str_val[self.cur_pos+1:]
                if self.is_valid(new_str):
                    self.str_val=new_str
                    self.process_event("edit",new_str,self)

    def on_edit(self,string,source):
        self.draw()
        self.to_screen()
        self.set_cursor()

    def on_change(self):
        val=self.get_val()
        self.str_val=self.val_to_str(val)
        self.cur_pos=0
        self.cur_origin=0

    def __init__(self):
        super(StringInput,self).__init__()
        self.add_event_listener("keypress",self.on_keypress)
        self.listeners["edit"]=[]
        self.add_event_listener("edit",self.on_edit)
        self.cur_pos=0
        self.cur_origin=0
        self.str_val=""
        self.maxh=1

    def is_valid(self,string):
        return True

    def set_cursor(self):
        screen.move(self.win_y+self.y,self.win_x+self.x+self.cur_pos-self.cur_origin)

    def draw(self):
        win=self.window
        s=self.str_val[self.cur_origin:self.cur_origin+self.w]
        s=s.encode('ascii','replace')
        s+="_"*(self.w-len(s))
        win.addstr(self.y,self.x,s)

    def to_screen(self):
        win=self.window
        win.refresh(self.y,self.x,self.win_y+self.y,self.win_x+self.x,self.win_y+self.y,self.win_x+self.x+self.w)

    def _compute_pass1(self):
        if self.readonly:
            self.maxw=len(self.str_val)
        else:
            self.maxw=-1

    def on_unfocus(self,arg,source):
        if not self.readonly:
            val=self.str_to_val(self.str_val)
            self.set_val(val)

class InputChar(StringInput):
    def val_to_str(self,val):
        return val and val or ""

    def str_to_val(self,s):
        if s=="":
            return False
        return s

class InputInteger(StringInput):
    def val_to_str(self,val):
        if val is False:
            return ""
        return str(val)

    def is_valid(self,string):
        try:
            x=int(string)
            return True
        except:
            return False

    def str_to_val(self,s):
        if s=="":
            return False
        return int(s)

class InputFloat(StringInput):
    def val_to_str(self,val):
        if val is False:
            return ""
        return "%.2f"%val

    def is_valid(self,string):
        try:
            x=float(string)
            return True
        except:
            return False

    def str_to_val(self,s):
        if s=="":
            return False
        return float(s)

class InputSelect(StringInput):
    def on_keypress(self,k,source):
        super(InputSelect,self).on_keypress(k,source)
        if k==ord("\n"):
            wg=SelectBox()
            wg.selection=self.field["selection"]
            wg.target_wg=self
            wg.show(self.y+1,self.x,self.str_val)

    def __init__(self):
        super(InputSelect,self).__init__()

    def val_to_str(self,val):
        if val is False:
            return ""
        for k,v in self.field["selection"]:
            if k==val:
                return v
        return ""

    def on_edit(self,string,source):
        if self.value:
            self.set_val(False)
        super(InputSelect,self).on_edit(string,source)

    def on_unfocus(self,arg,source):
        pass

class InputBoolean(StringInput):
    def val_to_str(self,val):
        return val and "Y" or "N"

    def is_valid(self,string):
        return string in ("Y","N")

    def str_to_val(self,s):
        if s in ("","N"):
            return False
        return True

class InputDate(StringInput):
    def on_keypress(self,k,source):
        super(InputDate,self).on_keypress(k,source)
        if k==ord("\n"):
            if not self.str_val:
                self.set_val(time.strftime("%Y-%m-%d"))
                self.draw()
                self.to_screen()
                self.set_cursor()

    def val_to_str(self,val):
        if val is False:
            return ""
        return val

    def str_to_val(self,s):
        if s=="":
            return False
        return s

class InputDatetime(StringInput):
    def val_to_str(self,val):
        if val is False:
            return ""
        return val

    def str_to_val(self,s):
        if s=="":
            return False
        return s

class InputM2O(StringInput):
    def on_keypress(self,k,source):
        super(InputM2O,self).on_keypress(k,source)
        if k==ord("\n"):
            wg=SearchPopup()
            wg.model=self.relation
            wg.target_wg=self
            wg.show(self.str_val)

    def on_edit(self,string,source):
        if self.value:
            self.set_val(False)
        super(InputM2O,self).on_edit(string,source)

    def val_to_str(self,val):
        if val is False:
            return ""
        return val[1]

class InputText(Input):
    def __init__(self):
        super(InputText,self).__init__()
        self.maxh=7
        self.maxw=-1

    def draw(self):
        win=self.window
        curses.textpad.rectangle(win,self.y,self.x,self.y+self.h-1,self.x+self.w-1)

    def set_cursor(self):
        screen.move(self.win_y+self.y+1,self.win_x+self.x+1)

class ObjRecord(object):
    def __init__(self):
        self.vals={}
        self.parent=None
        self.context={}
        self.browser=None

    def get_val(self,name):
        return self.vals[name]

    def set_val(self,name,val):
        self.vals[name]=val
        self.browser.call_record_changed(self,field=name)
        self.browser.call_record_changed(self)

    def set_vals(self,vals):
        self.vals=vals
        for name in vals:
            self.browser.call_record_changed(self,field=name)
        self.browser.call_record_changed(self)

class ObjBrowser(DeckPanel):
    def __init__(self,model,name=None,obj_ids=None,type=None,modes=None,view_ids=None,views=None,context=None):
        super(ObjBrowser,self).__init__()
        self.model=model
        self.obj_ids=obj_ids
        self.type=type or "form"
        self.modes=modes or ["tree","form"]
        self.view_ids=view_ids or {}
        self.name=name or ""
        self.context=context or {}
        self.cur_mode=self.modes[0]
        self.records=[]
        self.mode_wg={}
        for mode in self.modes:
            if mode=="tree":
                wg=TreeMode(type=self.type,modes=self.modes)
            elif mode=="form":
                wg=FormMode(type=self.type,modes=self.modes)
            else:
                continue
            self.mode_wg[mode]=wg
            self.add(wg)
            wg.maxh=-1
            if views and mode in views:
                wg.view=views[mode]

    def load_view(self):
        self.mode_wg[self.cur_mode].load_view()

    def read(self):
        self.mode_wg[self.cur_mode].read()

    def call_record_changed(self,record,field=None):
        self.mode_wg[self.cur_mode].call_record_changed(record,field)

class TreeMode(HorizontalPanel):
    def on_keypress(self,k,source):
        if k==curses.KEY_RIGHT:
            if source==self:
                i=self.commands.index(self.cur_cmd)
                i=(i+1)%len(self.commands)
                self.cur_cmd=self.commands[i]
                root_panel.set_cursor()
        elif k==curses.KEY_LEFT:
            if source==self:
                i=self.commands.index(self.cur_cmd)
                i=(i-1)%len(self.commands)
                self.cur_cmd=self.commands[i]
                root_panel.set_cursor()
        elif k==ord('\n'):
            if source==self:
                if self.cur_cmd=="N":
                    self.cur_mode="form"
                    self.load_view()
                    self.active_id=None
                    self.read()
                    self.cur_wg=self.form_mode
                    root_panel.compute()
                    root_panel.draw()
                    root_panel.refresh()
                    root_panel.clear_focus()
                    self.form_mode.set_focus()
                    root_panel.set_cursor()
                elif self.cur_cmd=="S":
                    if not self.active_id:
                        self.active_id=rpc_exec(self.model,"create",self.obj)
                    else:
                        rpc_exec(self.model,"write",self.active_id,self.obj)
                    self.read()
                    root_panel.set_cursor()
                elif self.cur_cmd=="D":
                    pass
                elif self.cur_cmd=="<":
                    pass
                elif self.cur_cmd==">":
                    pass
                elif self.cur_cmd=="T":
                    pass
                elif self.cur_cmd=="F":
                    pass

    def __init__(self,type,modes):
        super(TreeMode,self).__init__()
        self.borders=[1,1,1,1]
        self.add_event_listener("keypress",self.on_keypress)
        self.can_focus=True
        self.tree=None
        self.view=None
        self.commands=[]
        self.obj_pool={}
        self.rec_wgs={}
        if type=="tree":
            self.root_list=ListView()
            self.root_list.col=1
            self.root_list.names=["name"]
            self.root_list.maxh=-1
            self.root_list.borders=[0,0,0,0]
            self.add(self.root_list)
            def on_select(line_no,source):
                self.cur_root=self.root_objs[line_no]
                ids=self.cur_root[self.view["field_parent"]]
                new_ids=[id for id in self.cur_root[self.view["field_parent"]] if not id in self.obj_pool]
                if new_ids:
                    objs=rpc_exec(self.parent.model,"read",new_ids,self.view["fields"].keys()+[self.view["field_parent"]])
                    for obj in objs:
                        self.obj_pool[obj["id"]]=obj
                objs=[self.obj_pool[id] for id in ids]
                self.tree.delete_items()
                self.tree.add_items(objs)
                root_panel.compute()
                root_panel.draw()
                root_panel.refresh()
                root_panel.clear_focus()
                self.tree.set_focus()
                root_panel.set_cursor()
            self.root_list.add_event_listener("select",on_select)
        elif type=="form":
            self.commands+=["<",">"]
        self.commands+=[mode[0].upper() for mode in modes]
        self.cur_cmd="T"

    def draw(self):
        super(TreeMode,self).draw()
        if self.commands:
            win=self.window
            s=" ".join(self.commands)
            x=self.x+self.w-len(s)-3
            win.addch(self.y,x,curses.ACS_RTEE)
            x+=1
            win.addstr(self.y,x,s)
            x+=len(s)
            win.addch(self.y,x,curses.ACS_LTEE)

    def set_cursor(self):
        i=self.commands.index(self.cur_cmd)
        x=self.x+self.w-len(self.commands)*2-1+i*2
        screen.move(self.win_y+self.y,self.win_x+x)

    def parse(self,el,fields):
        if el.tag=="tree":
            wg=TreeView()
            wg.view_attrs=el.attrib
            headers=[]
            for child in el:
                name=child.attrib["name"]
                if child.tag=="field":
                    field=fields[name]
                    header=field["string"]
                else:
                    header=child.attrib["string"]
                headers.append(header)
            wg.col=len(headers)
            wg.make_header(headers)
            wg.maxw=-1
            def make_line(vals):
                record=ObjRecord()
                record.browser=self.parent
                self.parent.records.append(record)
                line=[]
                i=0
                for child in el:
                    if child.tag=="field":
                        name=child.attrib["name"]
                        field=fields[name]
                        if field["type"]=="char":
                            wg=InputChar()
                        elif field["type"]=="integer":
                            wg=InputInteger()
                        elif field["type"]=="float":
                            wg=InputFloat()
                        elif field["type"]=="boolean":
                            wg=InputBoolean()
                        elif field["type"]=="date":
                            wg=InputDate()
                        elif field["type"]=="datetime":
                            wg=InputDatetime()
                        elif field["type"]=="text":
                            wg=InputText()
                        elif field["type"]=="selection":
                            wg=InputSelect()
                        elif field["type"]=="many2one":
                            wg=InputM2O()
                        elif field["type"]=="many2many":
                            wg=InputM2M_list()
                        else:
                            raise Exception("invalid field type: %s"%field["type"])
                        wg.editable=False
                        wg.name=name
                        wg.field=field
                        wg.view_attrs=child.attrib
                        wg.record=record
                    elif child.tag=="button":
                        wg=Button()
                    wg.can_focus=i==0
                    self.rec_wgs.setdefault(record,{}).setdefault(wg.name,[]).append(wg)
                    line.append(wg)
                    i+=1
                record.set_vals(vals)
                return line
            wg.make_line=make_line
            return wg
        else:
            raise Exception("invalid tag in tree view: "+el.tag)

    def load_view(self):
        if not self.view:
            self.view=rpc_exec(self.parent.model,"fields_view_get",self.parent.view_ids.get("tree") or False,"tree",self.parent.context)
        arch=xml.etree.ElementTree.fromstring(self.view["arch"])
        if self.tree:
            self.remove(self.tree)
        self.tree=self.parse(arch,self.view["fields"])
        self.add(self.tree)
        self.tree.maxh=-1
        self.tree.maxw=-1
        self.tree.seps=[[(1,True),(0,False)],[(1,True)]]
        def on_select(line_no,source):
            if self.parent.type=="form":
                self.parent.cur_mode="form"
                self.parent.cur_record=self.parent.records[line_no]
                self.parent.load_view()
                self.parent.read()
                self.parent.cur_wg=self.parent.mode_wg["form"]
                root_panel.compute()
                root_panel.draw()
                root_panel.refresh()
                root_panel.clear_focus()
                root_panel.set_focus()
                root_panel.set_cursor()
            elif self.parent.type=="tree":
                obj=self.tree.lines[line_no]
                res=rpc_exec("ir.values","get","action","tree_but_open",[(self.parent.model,obj["id"])])
                if res:
                    act=res[0][2]
                    action(act["id"],_act=act)
        self.tree.add_event_listener("select",on_select)
        def on_open(item,source):
            ids=[id for id in item[self.view["field_parent"]] if not id in self.tree.items]
            if ids:
                objs=rpc_exec(self.parent.model,"read",item[self.view["field_parent"]],self.view["fields"].keys()+[self.view["field_parent"]])
                self.tree.add_items(objs)
        self.tree.add_event_listener("open",on_open)

    def read(self):
        if self.parent.type=="tree":
            self.root_objs=rpc_exec(self.parent.model,"read",self.parent.obj_ids,["name",self.view["field_parent"]])
            self.root_list.add_lines(self.root_objs)
            self.root_list.on_select(0)
        elif self.parent.type=="form":
            self.parent.records=[]
            lines=rpc_exec(self.parent.model,"read",self.parent.obj_ids,self.view["fields"].keys(),self.parent.context)
            self.tree.set_lines(lines)

    def call_record_changed(self,record,field=None):
        if field:
            for wg in self.rec_wgs[record].get(field,[]):
                wg.record_changed(record,field)
        else:
            for name,wgs in self.rec_wgs[record].items():
                for wg in wgs:
                    wg.record_changed(record)

class FormMode(ScrollPanel):
    def on_keypress(self,k,source):
        if k==curses.KEY_RIGHT:
            if source==self:
                i=self.commands.index(self.cur_cmd)
                i=(i+1)%len(self.commands)
                self.cur_cmd=self.commands[i]
                root_panel.set_cursor()
        elif k==curses.KEY_LEFT:
            if source==self:
                i=self.commands.index(self.cur_cmd)
                i=(i-1)%len(self.commands)
                self.cur_cmd=self.commands[i]
                root_panel.set_cursor()
        elif k==ord('\n'):
            if source==self:
                if self.cur_cmd=="N":
                    self.cur_mode="form"
                    self.load_view()
                    self.active_id=None
                    self.read()
                    self.cur_wg=self.form_mode
                    root_panel.compute()
                    root_panel.draw()
                    root_panel.refresh()
                    root_panel.clear_focus()
                    self.form_mode.set_focus()
                    root_panel.set_cursor()
                elif self.cur_cmd=="S":
                    if not self.active_id:
                        self.active_id=rpc_exec(self.model,"create",self.obj)
                    else:
                        rpc_exec(self.model,"write",self.active_id,self.obj)
                    self.read()
                    root_panel.set_cursor()
                elif self.cur_cmd=="D":
                    pass
                elif self.cur_cmd=="<":
                    pass
                elif self.cur_cmd==">":
                    pass
                elif self.cur_cmd=="T":
                    pass
                elif self.cur_cmd=="F":
                    pass

    def __init__(self,type,modes):
        super(FormMode,self).__init__()
        self.borders=[1,1,1,1]
        self.add_event_listener("keypress",self.on_keypress)
        self.can_focus=True
        self.form=None
        self.view=None
        self.commands=["N","S","D","<",">"]
        self.commands+=[mode[0].upper() for mode in modes]
        self.cur_cmd="F"
        self.rec_wgs={}

    def draw(self):
        super(FormMode,self).draw()
        if self.commands:
            win=self.window
            s=" ".join(self.commands)
            x=self.x+self.w-len(s)-3
            win.addch(self.y,x,curses.ACS_RTEE)
            x+=1
            win.addstr(self.y,x,s)
            x+=len(s)
            win.addch(self.y,x,curses.ACS_LTEE)

    def set_cursor(self):
        i=self.commands.index(self.cur_cmd)
        x=self.x+self.w-len(self.commands)*2-1+i*2
        screen.move(self.win_y+self.y,self.win_x+x)

    def parse(self,el,fields=None,panel=None,form=None):
        if el.tag=="form":
            wg=Form()
            wg.view_attrs=el.attrib
            wg.update_attrs()
            wg.record=self.parent.cur_record
            for child in el:
                self.parse(child,panel=wg,fields=fields,form=wg)
            return wg
        elif el.tag=="label":
            wg=Label()
            wg.view_attrs=el.attrib
            wg.update_attrs()
            wg.record=self.parent.cur_record
            panel.add(wg)
            return wg
        elif el.tag=="newline":
            panel.newline()
            return None
        elif el.tag=="separator":
            wg=Separator()
            wg.view_attrs=el.attrib
            wg.update_attrs()
            wg.record=self.parent.cur_record
            panel.add(wg)
            return wg
        elif el.tag=="button":
            wg=FormButton()
            wg.view_attrs=el.attrib
            wg.update_attrs()
            wg.record=self.parent.cur_record
            panel.add(wg)
            return wg
        elif el.tag=="field":
            field=fields[el.attrib["name"]]
            if not el.attrib.get("nolabel"):
                wg_l=FieldLabel()
                wg_l.field=field
                wg_l.view_attrs=el.attrib
                wg_l.update_attrs()
                wg_l.record=self.parent.cur_record
                wg_l.colspan=1
                panel.add(wg_l)
            if field["type"]=="char":
                wg=InputChar()
            elif field["type"]=="integer":
                wg=InputInteger()
            elif field["type"]=="float":
                wg=InputFloat()
            elif field["type"]=="boolean":
                wg=InputBoolean()
            elif field["type"]=="date":
                wg=InputDate()
            elif field["type"]=="datetime":
                wg=InputDatetime()
            elif field["type"]=="text":
                wg=InputText()
            elif field["type"]=="selection":
                wg=InputSelect()
            elif field["type"]=="many2one":
                wg=InputM2O()
            elif field["type"]=="one2many":
                model=field["relation"]
                modes=el.attrib.get("view_mode") and el.attrib["view_mode"].split(",") or None
                views=field["views"]
                wg=InputO2M(model,modes=modes,views=views)
                wg.load_view()
            elif field["type"]=="many2many":
                model=field["relation"]
                views=field["views"]
                wg=InputM2M(model,views=views)
                wg.load_view()
            else:
                raise Exception("unsupported field type: %s"%field["type"])
            wg.name=el.attrib["name"]
            wg.field=field
            wg.view_attrs=el.attrib
            wg.update_attrs()
            wg.record=self.parent.cur_record
            self.rec_wgs.setdefault(wg.name,[]).append(wg)
            panel.add(wg)
            return wg
        elif el.tag=="group":
            wg=Group()
            wg.view_attrs=el.attrib
            wg.update_attrs()
            wg.record=self.parent.cur_record
            for child in el:
                self.parse(child,fields=fields,panel=wg,form=form)
            panel.add(wg)
            return wg
        elif el.tag=="notebook":
            wg=Notebook()
            wg.view_attrs=el.attrib
            wg.update_attrs()
            wg.record=self.parent.cur_record
            wg.borders=[1,1,1,1]
            for elp in el:
                wg_p=Page()
                wg_p.view_attrs=elp.attrib
                wg_p.update_attrs()
                wg_p.record=self.parent.cur_record
                wg.add(wg_p)
                for child in elp:
                    self.parse(child,fields=fields,panel=wg_p,form=form)
            panel.add(wg)
            return wg
        else:
            raise Exception("invalid tag in form view: "+el.tag)

    def load_view(self):
        if self.form:
            return
        if not self.view:
            self.view=rpc_exec(self.parent.model,"fields_view_get",False,"form",self.parent.context)
        arch=xml.etree.ElementTree.fromstring(self.view["arch"])
        self.fields=self.view["fields"]
        if self.form:
            self.remove(self.form)
        self.form=self.parse(arch,self.view["fields"])
        self.add(self.form)
        self.form.model=self.parent.model
        self.form.maxh=-1

    def read(self):
        if self.parent.cur_record:
            vals=rpc_exec(self.parent.model,"read",[self.parent.cur_record.get_val("id")],self.view["fields"].keys(),self.parent.context)[0]
        else:
            record=ObjRecord()
            self.parent.cur_record=record
            vals=rpc_exec(self.parent.model,"default_get",self.view["fields"].keys(),self.parent.context or {})
            for name,val in vals.items():
                if val==False:
                    continue
                field=self.view["fields"][name]
                if field["type"]=="many2one":
                    val_=rpc_exec(field["relation"],"name_get",[val])[0]
                    vals[name]=val_
        self.parent.cur_record.set_vals(vals)

    def write(self):
        pass

    def call_record_changed(self,record,field=None):
        if field:
            for wg in self.rec_wgs.get(field,[]):
                wg.record_changed(record,field)
        else:
            for name,wgs in self.rec_wgs.items():
                for wg in wgs:
                    wg.record_changed(record)

class InputO2M(ObjBrowser,Input):
    def on_keypress(self,k,source):
        super(InputO2M,self).on_keypress(k,source)
        if k==ord("\n") and source==self:
            if self.cur_cmd=="N":
                wg=LinkPopup()
                wg.model=self.relation
                wg.string=self.string
                wg.view=self.view
                wg.target_wg=self
                wg.show()

    def on_change(self):
        val=self.get_val()
        self.obj_ids=val
        self.read()

    def __init__(self,model,modes=None,views=None):
        super(InputO2M,self).__init__(model,modes=modes,views=views)
        self.maxh=8

    def draw(self):
        win=self.window
        super(InputO2M,self).draw()
        x=self.x+1
        win.addch(self.y,x,curses.ACS_RTEE)
        x+=1
        s=" "+self.string+" "
        win.addstr(self.y,self.x+2,s)
        x+=len(s)
        win.addch(self.y,x,curses.ACS_LTEE)

    def load_view(self):
        super(InputO2M,self).load_view()
        self.mode_wg["tree"].tree.seps=[[(0,False)],[(1,True)]]

class InputM2M(ObjBrowser,Input):
    def __init__(self,model,modes=None,views=None):
        super(InputM2M,self).__init__(model,modes=modes,views=views)
        self.maxh=8
        self.maxw=-1

    def load_view(self):
        super(InputM2M,self).load_view()
        self.mode_wg["tree"].tree.seps=[[(0,False)],[(1,True)]]

class InputM2M_list(StringInput):
    def on_keypress(self,k,source):
        super(InputM2M_list,self).on_keypress(k,source)
        if k==ord("\n"):
            wg=SearchPopup()
            wg.model=self.relation
            wg.target_wg=self
            wg.show(self.str_val)

    def val_to_str(self,val):
        if val is False:
            return ""
        return "(%d)"%len(val)

    def _compute_pass1(self):
        if self.readonly:
            self.maxw=len(self.str_val)
        else:
            self.maxw=-1

class SelectBox(ListView):
    def on_select(self,line_no):
        val=self.selection[line_no][0]
        self.target_wg.set_val(val)

    def __init__(self):
        super(SelectBox,self).__init__()
        self.col=1
        self.names=["string"]

    def show(self,y,x,query):
        for k,v in self.selection:
            self.add_line({"string":v,"name":k})
        self._compute_pass1()
        self.w=self.maxw
        self.y=y
        self.x=x
        self._compute_pass2()
        self.draw()
        screen.refresh()
        self.set_focus()

class SearchPopup(Table):
    def __init__(self):
        super(SearchPopup,self).__init__(model)
        self.col=1
        self.title=Label()
        self.add(self.title)
        self.obj_list=ObjBrowser(model,modes=["tree"])
        self.obj_list.commands=[]
        self.obj_list.can_focus=False
        self.add(self.obj_list)
        buttons=Group()
        buttons.col=4
        self.add(buttons)
        btn_new=Button()
        btn_new.string="New"
        buttons.add(btn_new)
        btn_find=Button()
        btn_find.string="Find"
        buttons.add(btn_find)
        btn_cancel=Button()
        btn_cancel.string="Cancel"
        buttons.add(btn_cancel)
        btn_ok=Button()
        btn_ok.string="OK"
        buttons.add(btn_ok)

    def show(self,query):
        self.obj_list.model=self.model
        self.obj_list.load_view()
        self.obj_list.tree_mode.tree.listeners["select"]=[]
        def on_select(line_no,source):
            obj=self.obj_list.tree_mode.objs[line_no]
            self.target_wg.set_val((obj["id"],obj["name"]))
            root_panel.close_popup(self)
            root_panel.compute()
            root_panel.draw()
            root_panel.refresh()
            root_panel.clear_focus()
            self.target_wg.set_focus()
            self.target_wg.set_cursor()
        self.obj_list.tree_mode.tree.add_event_listener("select",on_select)
        self.title.string="Search: "+self.obj_list.tree_mode.tree.string
        self.string=self.obj_list.tree_mode.tree.string
        res=rpc_exec(self.model,"name_search",query)
        if len(res)==1:
            self.target_wg.set_val(res[0])
            self.target_wg.draw()
            self.target_wg.set_cursor()
        else:
            self.obj_list.obj_ids=[r[0] for r in res]
            self.obj_list.read()
            root_panel.show_popup(self)

class LinkPopup(Table):
    def on_ok(self,arg,source):
        # XXX
        root_panel.close_popup(self)

    def __init__(self):
        super(LinkPopup,self).__init__(model)
        self.col=1
        self.title=Label()
        self.add(self.title)
        self.obj_list=ObjBrowser(model,modes=["form"])
        self.obj_list.commands=[]
        self.obj_list.can_focus=False
        self.add(self.obj_list)
        buttons=Group()
        buttons.col=2
        self.add(buttons)
        btn_cancel=Button()
        btn_cancel.string="Cancel"
        buttons.add(btn_cancel)
        btn_ok=Button()
        btn_ok.add_event_listener("push",self.on_ok)
        btn_ok.string="OK"
        buttons.add(btn_ok)

    def show(self):
        self.obj_list.model=self.model
        self.obj_list.view=self.view
        self.obj_list.load_view()
        self.obj_list.form.parent=self.parent
        self.title.string="Link: "+self.string
        self.obj_list.read()
        root_panel.show_popup(self)

class StatusPanel(Table):
    def __init__(self):
        super(StatusPanel,self).__init__()
        self.label=Label()
        self.col=1
        self.add(self.label)

    def set_user(self,user):
        self.user=user
        self.update()

    def update(self):
        self.label.string="%s:%d [%s] %s"%(opts.host,opts.port,dbname,self.user)

class RootPanel(DeckPanel):
    def on_keypress(self,k,source):
        if k in (ord("\t"),curses.KEY_DOWN):
            ind=self.get_tabindex()
            i=ind.index(source)
            i=(i+1)%len(ind)
            log("move down",source,getattr(source,"name",""),"->",ind[i],getattr(ind[i],"name",""))
            self.clear_focus()
            ind[i].set_focus()
            self.set_cursor()
        elif k==curses.KEY_UP:
            ind=self.get_tabindex()
            i=ind.index(source)
            i=(i-1)%len(ind)
            self.clear_focus()
            ind[i].set_focus()
            self.set_cursor()

    def __init__(self):
        super(RootPanel,self).__init__()
        self.main=VerticalPanel()
        self.add(self.main)
        self.windows=TabPanel()
        self.windows.maxh=-1
        self.main.add(self.windows)
        self.status=StatusPanel()
        self.status.maxh=1
        self.main.add(self.status)
        self.add_event_listener("keypress",self.on_keypress)
        self.window=screen
        self.win_y=0
        self.win_x=0

    def new_window(self,act):
        name=act.get("name")
        model=act["res_model"]
        type=act.get("view_type")
        modes=act.get("view_mode") and act["view_mode"].split(",") or None
        domain=act.get("domain") and eval(act["domain"]) or []
        context=act.get("context") and eval(act["context"]) or {}
        view_ids={}
        if act.get("view_id"):
            view_ids[modes[0]]=act["view_id"][0]
        obj_ids=rpc_exec(model,"search",domain,0,10,context)
        win=ObjBrowser(model,name=name,obj_ids=obj_ids,type=type,modes=modes,view_ids=view_ids,context=context)
        win.maxh=-1
        self.windows.add(win)
        self.windows.set_cur_wg(win)
        win.load_view()
        win.read()
        root_panel.compute()
        root_panel.draw()
        root_panel.refresh()
        root_panel.clear_focus()
        root_panel.set_focus()
        root_panel.set_cursor()

    def set_cursor(self):
        wg_f=self.get_focus()
        if wg_f:
            wg_f.set_cursor()

    def show_popup(self,wg):
        self.add(wg)
        self.cur_wg=wg
        self.compute()
        self.draw()
        self.refresh()
        self.clear_focus()
        self.set_focus()
        self.set_cursor()

    def close_popup(self,wg):
        if wg!=self.cur_wg:
            raise Exception("popup is not currently active")
        self._childs.pop()
        self.cur_wg=self._childs[-1]

    def compute(self):
        super(RootPanel,self).compute(24,80,0,0)

    def draw(self):
        screen.clear()
        super(RootPanel,self).draw()

    def refresh(self):
        screen.refresh()
        super(RootPanel,self).refresh()

def view_to_s(el,d=0):
    s="  "*d+el.tag
    for k in sorted(el.attrib.keys()):
        v=el.attrib[k]
        s+=" %s=%s"%(k,v)
    for child in el:
        s+="\n"+view_to_s(child,d+1)
    return s

def act_window(act_id,_act=None):
    if _act:
        act=_act
    else:
        act=rpc_exec("ir.actions.act_window","read",act_id,["name","res_model","domain","view_type","view_mode","view_id","context"])
    root_panel.new_window(act)

def action(act_id,_act=None):
    if _act:
        act=_act
    else:
        act=rpc_exec("ir.actions.actions","read",act_id,["name","type"])
    if act["type"]=="ir.actions.act_window":
        act_window(act_id,_act)
    else:
        raise Exception("Unsupported action type: %s"%act["type"])

def start(stdscr):
    global screen,root_panel
    screen=stdscr
    screen.keypad(1)
    root_panel=RootPanel()
    user=rpc_exec("res.users","read",uid,["name","action_id","menu_id"])
    root_panel.status.set_user(user["name"])
    action(user["action_id"][0])
    while 1:
        k=screen.getch()
        if k==ord('D'):
            set_trace()
        source=root_panel.get_focus()
        if not source:
            raise Exception("could not find key press source widget")
        root_panel.process_event("keypress",k,source)
curses.wrapper(start)
