#!/usr/bin/python
##############################################################################
#
#    OpenERP Text Client
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
import curses.panel
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

def log(*args):
    msg=" ".join([str(a) for a in args])
    screen.addstr(msg+"\n")
    screen.refresh()

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

def eval_dom(dom,obj):
    for (name,oper,param) in dom:
        val=obj[name]
        if oper=="=":
            res=val==param
        elif oper=="!=":
            res=val!=param
        elif oper=="in":
            res=val in param
        elif oper=="not in":
            res=not val in param
        else:
            raise Exception("unsupported operator: %s"%oper)
        if not res:
            return False
    return True

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
        self.field_attrs={}
        self.states_f={}
        self.view_attrs={}
        self.states_v=None
        self.attrs_v={}
        self.colspan=1
        self.rowspan=1
        self.string=""
        self.readonly=False
        self.invisible=False
        self.states=None
        self.listeners={
            "keypress": [],
            "unfocus": [],
        }
        self.add_event_listener("unfocus",self.on_unfocus)

    def set_field_attrs(self,attrs):
        for k,v in attrs.items():
            if k in ("string","readonly","states","size","select","required","domain","relation","context","digits","change_default","help","selection","translate","invisible"):
                self.field_attrs[k]=v
            elif k in ("views","type"):
                pass
            else:
                raise Exception("unsupported field attribute: %s"%k)
        for k,v in self.field_attrs.items():
            setattr(self,k,v)

    def set_view_attrs(self,attrs):
        for k,v in attrs.items():
            if k in ("string","name","on_change","domain","context","type","widget","sum","icon","default_get","colors","color","password","editable"):
                val=v
            elif k in ("colspan","col"):
                val=int(v)
            elif k in ("readonly","select","required","nolabel","invisible"):
                val=eval(v) and True or False
            elif k in ("states","mode","view_mode"):
                val=v.split(",")
            elif k in ("attrs"):
                val=eval(v)
            else:
                raise Exception("unsupported view attribute: %s"%k)
            self.view_attrs[k]=val
        for k,v in self.view_attrs.items():
            setattr(self,k,v)

    def update_attrs(self,vals):
        state=vals.get("state")
        update=("readonly","required","invisible")
        for k,v in self.field_attrs.items():
            if k in update:
                setattr(self,k,v)
        states=self.field_attrs.get("states")
        if states and state in states:
            for k,v in states[state]:
                if k in update:
                    setattr(self,k,v)
                else:
                    raise Exception("attribute can not be updated: %s"%k)
        for k,v in self.view_attrs.items():
            if k in update:
                setattr(self,k,v)
        states=self.view_attrs.get("states")
        if states!=None:
            self.invisible=not state in states
        attrs=self.view_attrs.get("attrs")
        if attrs:
            for k,dom in attrs.items():
                if k in update:
                    setattr(self,k,eval_dom(dom,vals))
                else:
                    raise Exception("attribute can not be updated: %s"%k)

    def set_vals(self,vals):
        self.update_attrs(vals)

    def to_s(self,d=0):
        s="  "*d
        s+=" "+self.__class__.__name__
        for name in dir(self):
            if name.startswith("_"):
                continue
            if not name in ("x","y","maxw","maxh","h","w","string","col","colspan","value","can_focus","has_focus","borders","padding","seps"):
                continue
            val=getattr(self,name)
            if callable(val):
                continue
            s+=" %s=%s"%(name,str(val))
        return s

    def draw(self,win):
        raise Exception("method not implemented")

    def refresh(self,win):
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

    def set_cursor(self):
        screen.move(self.y,self.x)

    def get_focus(self):
        return self.has_focus and self or None

class Panel(Widget):
    def __init__(self):
        super(Panel,self).__init__()
        self._childs=[]

    def add(self,wg):
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

    def draw(self,win):
        for c in self._vis_childs():
            c.draw(win)

    def refresh(self,win):
        for c in self._vis_childs():
            c.refresh(win)

    def set_vals(self,vals):
        super(Panel,self).set_vals(vals)
        for c in self._childs:
            c.set_vals(vals)

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
        self.pad=None
        self.y0=0

    def _compute_pass1(self):
        wg=self._childs[0]
        wg._compute_pass1()
        if self.maxw is None:
            self.maxw=wg.maxw
            if self.maxw!=-1:
                self.maxw+=self.borders[1]+self.borders[3]+1
        if self.maxh is None:
            self.maxh=wg.maxh
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
            wg._compute_pass2()

    def draw(self,win):
        wg=self._childs[0]
        if not self.pad:
            #self.pad=curses.newpad(wg.h,wg.w)
            self.pad=curses.newpad(wg.h+10,wg.w+10) #XXX
        self.pad.clear()
        wg.draw(self.pad)
        if self.borders[0]:
            curses.textpad.rectangle(win,self.y,self.x,self.y+self.h-1,self.x+self.w-1)
        win.vline(self.y,self.x+self.w-1,curses.ACS_BLOCK,self.h)
        win.vline(self.y,self.x+self.w-1,curses.ACS_CKBOARD,3)

    def refresh(self,win):
        self.pad.refresh(self.y0,0,self.y+self.borders[0],self.x+self.borders[3],self.y+self.h-1-self.borders[2],self.x+self.w-1-self.borders[1]-1)
        wg=self._childs[0]
        wg.refresh(self.pad)

class DeckPanel(Panel):
    def on_keypress(self,k,source):
        if k==curses.KEY_RIGHT:
            if source==self:
                i=self._childs.index(self.cur_wg)
                i=(i+1)%len(self._childs)
                self.cur_wg=self._childs[i]
                root_panel.set_cursor()
        elif k==curses.KEY_LEFT:
            if source==self:
                i=self._childs.index(self.cur_wg)
                i=(i-1)%len(self._childs)
                self.cur_wg=self._childs[i]
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
        for wg in self._vis_childs():
            if hasattr(wg,"_compute_pass2"):
                wg._compute_pass2()

    def draw(self,win):
        if self.borders[0]:
            curses.textpad.rectangle(win,self.y,self.x,self.y+self.h-1,self.x+self.w-1)
        if self.cur_wg:
            self.cur_wg.draw(win)

    def refresh(self,win):
        if self.cur_wg:
            self.cur_wg.refresh(win)

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

    def draw(self,win):
        i=0
        for wg in self._childs:
            x=self.tab_x[i]
            s="%d %s "%(i+1,wg.name)
            if wg==self.cur_wg:
                win.addstr(self.y,x,s,curses.A_REVERSE)
            else:
                win.addstr(self.y,x,s)
            i+=1
        super(TabPanel,self).draw(win)

    def set_cursor(self):
        if not self.cur_wg:
            return
        i=self._childs.index(self.cur_wg)
        x=self.tab_x[i]
        screen.move(self.y,x)

class Notebook(DeckPanel):
    def __init__(self):
        super(Notebook,self).__init__()
        self.can_focus=True
        self.tab_x=[]
        self.borders=[1,1,1,1]

    def compute_tabs(self):
        x=self.x+3
        self.tab_x=[]
        for wg in self._childs:
            self.tab_x.append(x)
            x+=len(wg.string)+3

    def _compute_pass2(self):
        super(Notebook,self)._compute_pass2()
        self.compute_tabs()

    def draw(self,win):
        super(Notebook,self).draw(win)
        i=0
        for wg in self._childs:
            x=self.tab_x[i]
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
        i=self._childs.index(self.cur_wg)
        x=self.tab_x[i]
        screen.move(self.y,x)

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
        if not self._childs:
            return
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
        for child in self._vis_childs():
            if hasattr(child,"_compute_pass2"):
                child._compute_pass2()

    def draw(self,win):
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
        super(Table,self).draw(win)

class Form(Table):
    def __init__(self):
        super(Form,self).__init__()
        self.relation=None
        self.string=""
        self.maxw=-1
        self.seps=[[(0,False)],[(1,False)]]
        self.col=4
        self.input_wg={}
        self.active_id=None
        self.parent=None
        self.context={}

    def apply_on_change(self,on_change):
        i=on_change.find("(")
        if i==-1:
            raise Exception("invalid on_change expression: %s"%on_change)
        func=on_change[:i].strip()
        args_str=on_change[i:]
        class EnvDict(dict):
            def __getitem__(self_,item):
                return self.get_val(item)
        env=EnvDict()
        try:
            args=eval(args_str,env)
            if type(args)!=type(()):
                args=(args,)
        except Exception,e:
            raise Exception("invalid on_change expression: %s"%on_change)
        ids=self.active_id and [self.active_id] or []
        res=rpc_exec(self.model,func,ids,*args)
        value=res["value"]
        for k,v in value.items():
            self.set_val(k,v,apply_on_change=False)

    def get_val(self,name):
        if name=="parent":
            if not self.parent:
                raise Exception("form does not have parent")
            class Parent(object):
                def __getattr__(self_,name):
                    return self.parent.get_val(name)
            return Parent()
        elif name=="context":
            return self.context
        else:
            return self.input_wg[name].get_val()

    def set_val(self,name,val,apply_on_change=True):
        return self.input_wg[name].set_val(val,apply_on_change)

    def get_vals(self):
        vals={}
        for name in self.input_wg:
            vals[name]=self.get_val(name)
        return vals

class Group(Table):
    def __init__(self):
        super(Group,self).__init__()
        self.string=""
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
        self.borders=[1,1,1,1]
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
        line=self.make_line(vals)
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
        screen.move(self.y+self.borders[0]+(self.has_header and 1+self.seps[0][0][0] or 0),self.x+self.borders[3])

    def draw(self,win):
        super(ListView,self).draw(win)
        x=self.x+self.borders[3]
        w=self.w-self.borders[1]-self.borders[3]
        for sel in self.selected:
            wg=self._childs[sel*self.col]
            y=wg.y
            win.chgat(y,x,w,curses.A_BOLD)

    def set_vals(self,lines):
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
                if not line["_open"] and item[self.field_parent]:
                    self.process_event("open",item,self)
                    items=[self.items[id] for id in item[self.field_parent]]
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
        self.field_parent=None
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
            line["name"]="  "*d+(item[self.field_parent] and "/" or "")+item["name"]
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

    def draw(self,win):
        s=self.string[:self.w]
        win.addstr(self.y,self.x,s)

class Separator(Widget):
    def __init__(self):
        super(Separator,self).__init__()
        self.string=""
        self.maxh=1
        self.maxw=-1

    def draw(self,win):
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

    def draw(self,win):
        s="["+self.string[:self.w-2]+"]"
        win.addstr(self.y,self.x,s)

    def set_cursor(self):
        screen.move(self.y,self.x+1)

class FormButton(Button):
    def on_push(self,arg,source):
        type=getattr(self,"type","wizard")
        if type=="wizard":
            form=self.form_wg
            list_wg=form.list_wg
            rpc_exec_wkf(form.model,self.name,list_wg.active_id)
            list_wg.load_data()
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

    def draw(self,win):
        s=self.string[:self.w-1]
        s+=":"
        win.addstr(self.y,self.x,s)

class Input(Widget):
    def __init__(self):
        super(Input,self).__init__()
        self.name=None
        self.can_focus=True
        self.under=True
        self.value=False

    def set_vals(self,vals):
        super(Input,self).set_vals(vals)
        if self.name in vals:
            self.set_val(vals[self.name])

    def get_val(self):
        return self.value

    def set_val(self,val,apply_on_change=True):
        if val!=self.value:
            self.value=val
            if apply_on_change:
                on_change=getattr(self,"on_change",None)
                if on_change:
                    self.form_wg.apply_on_change(on_change)

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
                self.draw(screen)
            self.set_cursor()
        elif k==curses.KEY_RIGHT:
            self.cur_pos=min(self.cur_pos+1,len(self.str_val))
            if self.cur_pos-self.cur_origin>self.w-1:
                self.cur_origin=self.cur_pos-self.w+1
                self.draw(screen)
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
        self.draw(screen)
        self.set_cursor()

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
        screen.move(self.y,self.x+self.cur_pos-self.cur_origin)

    def set_val(self,val,apply_on_change=True):
        super(StringInput,self).set_val(val,apply_on_change)
        self.str_val=self.val_to_str(self.value)
        self.cur_pos=0
        self.cur_origin=0

    def draw(self,win):
        s=self.str_val[self.cur_origin:self.cur_origin+self.w]
        s+="_"*(self.w-len(s))
        win.addstr(self.y,self.x,s)

    def _compute_pass1(self):
        if self.readonly:
            self.maxw=len(self.str_val)
        else:
            self.maxw=-1

    def on_unfocus(self,arg,source):
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
            wg.selection=self.selection
            wg.target_wg=self
            wg.show(self.y+1,self.x,self.str_val)

    def __init__(self):
        super(InputSelect,self).__init__()
        self.selection=[]

    def val_to_str(self,val):
        if val is False:
            return ""
        for k,v in self.selection:
            if k==val:
                return v
        raise Exception("invalid selection value: %s"%self.value)

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

    def set_val(self,val,apply_on_change=True):
        if type(val)==type(1):
            res=rpc_exec(self.relation,"name_get",[val])
            val=res[0]
        super(InputM2O,self).set_val(val,apply_on_change)

    def get_val(self):
        if self.value is False:
            return False
        return self.value[0]

    def val_to_str(self,val):
        if val is False:
            return ""
        return val[1]

    def on_unfocus(self,arg,source):
        self.set_val(self.value)
        self.draw(screen)
        self.set_cursor()

class InputText(Input):
    def __init__(self):
        super(InputText,self).__init__()
        self.maxh=7
        self.maxw=-1

    def draw(self,win):
        curses.textpad.rectangle(win,self.y,self.x,self.y+self.h-1,self.x+self.w-1)

    def set_cursor(self):
        screen.move(self.y+1,self.x+1)

class ObjTree(HorizontalPanel):
    def __init__(self):
        super(ObjTree,self).__init__()
        self.model=None
        self.domain=None
        self.context=None
        self.view_id=None
        self.name=None
        self.field_parent=None
        self.root_list=ListView()
        self.root_list.col=1
        self.root_list.names=["name"]
        self.root_list.maxh=-1
        self.root_list.borders=[0,0,0,0]
        self.add(self.root_list)
        self.objs={}
        def on_select(line_no,source):
            self.cur_root=self.root_objs[line_no]
            ids=self.cur_root[self.field_parent]
            new_ids=[id for id in self.cur_root[self.field_parent] if not id in self.objs]
            if new_ids:
                objs=rpc_exec(self.model,"read",new_ids,self.fields.keys()+[self.field_parent])
                for obj in objs:
                    self.objs[obj["id"]]=obj
            objs=[self.objs[id] for id in ids]
            self.tree.delete_items()
            self.tree.add_items(objs)
            root_panel.compute()
            root_panel.draw()
            root_panel.refresh()
            root_panel.clear_focus()
            self.tree.set_focus()
        self.root_list.add_event_listener("select",on_select)

    def parse_tree(self,el,fields):
        if el.tag=="tree":
            wg=TreeView()
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
            def make_line(vals):
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
                            wg.selection=field["selection"]
                        wg.readonly=True
                        wg.under=False
                        wg.set_val(vals[name])
                    elif child.tag=="button":
                        wg=Button()
                    if i==0:
                        wg.can_focus=True
                    line.append(wg)
                    i+=1
                return line
            wg.make_line=make_line
            return wg

    def load_view(self):
        self.view=rpc_exec(self.model,"fields_view_get",self.view_id,"tree",self.context)
        self.field_parent=self.view["field_parent"]
        self.fields=self.view["fields"]
        self.arch=xml.etree.ElementTree.fromstring(self.view["arch"])
        self.tree=self.parse_tree(self.arch,self.fields)
        self.tree.field_parent=self.field_parent
        self.tree.maxh=-1
        self.tree.maxw=-1
        self.tree.borders=[0,0,0,0]
        self.tree.seps=[[(1,True),(0,False)],[(1,True)]]
        self.add(self.tree)
        def on_open(item,source):
            ids=[id for id in item[self.field_parent] if not id in self.tree.items]
            if ids:
                objs=rpc_exec(self.model,"read",item[self.field_parent],self.fields.keys()+[self.field_parent])
                self.tree.add_items(objs)
        self.tree.add_event_listener("open",on_open)
        def on_select(line_no,source):
            obj=self.tree.lines[line_no]
            res=rpc_exec("ir.values","get","action","tree_but_open",[(self.model,obj["id"])])
            if res:
                act=res[0][2]
                action(act["id"],_act=act)
        self.tree.add_event_listener("select",on_select)

    def load_data(self):
        self.root_ids=rpc_exec(self.model,"search",self.domain)
        self.root_objs=rpc_exec(self.model,"read",self.root_ids,["name",self.field_parent])
        self.root_list.add_lines(self.root_objs)
        self.root_list.on_select(0)

class ObjList(DeckPanel):
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

    def __init__(self):
        super(ObjList,self).__init__()
        self.model=None
        self.obj_ids=None
        self.context=None
        self.modes=None
        self.string=None
        self.cur_mode=None
        self.view={}
        self.fields={}
        self.active_id=None
        self.tree_mode=None
        self.form_mode=None
        self.commands=["N","S","D","<",">","L","F"]
        self.cur_cmd="N"
        self.borders=[1,1,1,1]
        self.can_focus=True

    def load_view(self):
        if self.cur_mode=="tree" and not self.tree_mode:
            self.tree_mode=TreeMode()
            self.tree_mode.list_wg=self
            self.add(self.tree_mode)
            self.tree_mode.model=self.model
            self.tree_mode.context=self.context
            self.tree_mode.maxh=-1
            self.tree_mode.load_view(self.view.get("tree"))
        elif self.cur_mode=="form" and not self.form_mode:
            self.form_mode=FormMode()
            self.form_mode.list_wg=self
            self.add(self.form_mode)
            self.form_mode.model=self.model
            self.form_mode.context=self.context
            self.form_mode.maxh=-1
            self.form_mode.load_view(self.view.get("form"))
        else:
            raise Exception("unsupported view mode: %s"%self.cur_mode)

    def load_data(self):
        if self.cur_mode=="tree":
            self.tree_mode.obj_ids=self.obj_ids
            self.tree_mode.load_data()
        elif self.cur_mode=="form":
            self.form_mode.load_data()

    def draw(self,win):
        super(ObjList,self).draw(win)
        if self.commands:
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
        screen.move(self.y,x)

class TreeMode(VerticalPanel):
    def __init__(self):
        super(TreeMode,self).__init__()
        self.tree=None

    def parse_tree(self,el,fields):
        if el.tag=="tree":
            wg=ListView()
            wg.set_view_attrs(el.attrib)
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
                            wg.selection=field["selection"]
                        elif field["type"]=="many2one":
                            wg=InputM2O()
                        else:
                            raise Exception("invalid field type: %s"%field["type"])
                        wg.readonly=True
                        wg.under=False
                        wg.set_field_attrs(field)
                        wg.set_view_attrs(el.attrib)
                        if name in vals:
                            wg.set_val(vals[name])
                    elif child.tag=="button":
                        wg=Button()
                    wg.can_focus=i==0
                    line.append(wg)
                    i+=1
                return line
            wg.make_line=make_line
        return wg

    def load_view(self,view=None):
        if self.tree:
            return
        if view:
            self.view=view
        else:
            self.view=rpc_exec(self.model,"fields_view_get",False,"tree",self.context or {})
        arch=xml.etree.ElementTree.fromstring(self.view["arch"])
        self.tree=self.parse_tree(arch,self.view["fields"])
        self.tree.maxh=-1
        self.tree.seps=[[(1,True),(0,False)],[(1,True)]]
        self.add(self.tree)
        def on_select(line_no,source):
            self.list_wg.cur_mode="form"
            self.list_wg.load_view()
            self.list_wg.active_id=self.objs[line_no]["id"]
            self.list_wg.load_data()
            self.list_wg.cur_wg=self.list_wg.form_mode
            root_panel.compute()
            root_panel.draw()
            root_panel.refresh()
            root_panel.clear_focus()
            root_panel.set_focus()
            root_panel.set_cursor()
        self.tree.add_event_listener("select",on_select)

    def load_data(self):
        self.objs=rpc_exec(self.model,"read",self.list_wg.obj_ids,self.view["fields"].keys(),self.eval_context() or {})
        self.tree.set_vals(self.objs)

    def eval_context(self):
        if not self.context:
            return {}
        return eval(self.context)

class FormMode(ScrollPanel):
    def __init__(self):
        super(FormMode,self).__init__()
        self.form=None

    def parse_form(self,el,fields=None,panel=None,form=None):
        if el.tag=="form":
            wg=Form()
            for child in el:
                self.parse_form(child,panel=wg,fields=fields,form=wg)
            return wg
        elif el.tag=="tree":
            wg=ListView()
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
                            wg.selection=field["selection"]
                        elif field["type"]=="many2one":
                            wg=InputM2O()
                        else:
                            raise Exception("invalid field type: %s"%field["type"])
                        wg.readonly=True
                        wg.under=False
                        wg.set_val(vals[name])
                    elif child.tag=="button":
                        wg=Button()
                    wg.can_focus=i==0
                    line.append(wg)
                    i+=1
                return line
            wg.make_line=make_line
            return wg
        elif el.tag=="label":
            wg=Label()
            wg.set_view_attrs(el.attrib)
            panel.add(wg)
            return wg
        elif el.tag=="newline":
            panel.newline()
            return None
        elif el.tag=="separator":
            wg=Separator()
            wg.set_view_attrs(el.attrib)
            panel.add(wg)
            return wg
        elif el.tag=="button":
            wg=FormButton()
            wg.set_view_attrs(el.attrib)
            wg.form_wg=form
            panel.add(wg)
            return wg
        elif el.tag=="field":
            field=fields[el.attrib["name"]]
            if not el.attrib.get("nolabel"):
                wg_l=FieldLabel()
                wg_l.set_field_attrs(field)
                wg_l.set_view_attrs(el.attrib)
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
                wg.selection=field["selection"]
            elif field["type"]=="many2one":
                wg=InputM2O()
            elif field["type"]=="one2many":
                wg=InputO2M()
                wg.model=field["relation"]
                view_mode=el.attrib.get("view_mode") or "tree,form"
                wg.modes=view_mode.split(",")
                wg.cur_mode=wg.modes[0]
                wg.view=field["views"]
                wg.load_view()
            elif field["type"]=="many2many":
                wg=InputM2M()
                wg.model=field["relation"]
                wg.view=field["views"]
                wg.load_view()
            else:
                raise Exception("unsupported field type: %s"%field["type"])
            wg.name=el.attrib["name"]
            wg.set_field_attrs(field)
            wg.colspan=2
            wg.set_view_attrs(el.attrib)
            if not el.attrib.get("nolabel"):
                wg.colspan-=1
            wg.form_wg=form
            form.input_wg[wg.name]=wg
            panel.add(wg)
            return wg
        elif el.tag=="group":
            wg=Group()
            wg.set_view_attrs(el.attrib)
            for child in el:
                self.parse_form(child,fields=fields,panel=wg,form=form)
            panel.add(wg)
            return wg
        elif el.tag=="notebook":
            wg=Notebook()
            wg.set_view_attrs(el.attrib)
            wg.borders=[1,1,1,1]
            for elp in el:
                wg_p=Page()
                wg_p.set_view_attrs(elp.attrib)
                wg.add(wg_p)
                for child in elp:
                    self.parse_form(child,fields=fields,panel=wg_p,form=form)
            panel.add(wg)
            return wg
        else:
            raise Exception("invalid tag: "+el.tag)

    def load_view(self,view=None):
        if self.form:
            return
        if view:
            self.view=view
        else:
            self.view=rpc_exec(self.model,"fields_view_get",False,"form",self.context or {})
        arch=xml.etree.ElementTree.fromstring(self.view["arch"])
        self.fields=self.view["fields"]
        self.form=self.parse_form(arch,self.view["fields"])
        self.form.model=self.model
        self.form.maxh=-1
        self.add(self.form)
        self.form.list_wg=self

    def load_data(self):
        if self.list_wg.active_id:
            self.obj=rpc_exec(self.model,"read",[self.list_wg.active_id],self.view["fields"].keys(),self.eval_context() or {})[0]
        else:
            self.obj=rpc_exec(self.model,"default_get",self.view["fields"].keys(),self.context or {})
            for name,val in self.obj.items():
                if val==False:
                    continue
                field=self.view["fields"][name]
                if field["type"]=="many2one":
                    val_=rpc_exec(field["relation"],"name_get",[val])[0]
                    self.obj[name]=val_
        self.form.set_vals(self.obj)

    def eval_context(self):
        if not self.context:
            return {}
        return eval(self.context)

class TreeWindow(ObjTree):
    def __init__(self):
        super(TreeWindow,self).__init__()
        self.name=None

class ListWindow(ObjList):
    def on_keypress(self,k,source):
        super(ListWindow,self).on_keypress(k,source)
        if source==self and k==ord("\n"):
            if self.cur_cmd=="S":
                vals=self.form.get_vals()
                if not self.active_id:
                    self.active_id=rpc_exec(self.model,"create",vals)
                else:
                    rpc_exec(self.model,"write",self.active_id,vals)
                self.load_data()
                root_panel.set_cursor()

    def __init__(self):
        super(ListWindow,self).__init__()
        self.name=None

class InputO2M(ObjList,Input):
    def on_keypress(self,k,source):
        super(InputO2M,self).on_keypress(k,source)
        if k==ord("\n") and source==self:
            if self.cur_cmd=="N":
                wg=LinkPopup()
                wg.model=self.relation
                wg.string=self.string
                wg.view=self.view
                wg.parent=self.form_wg
                wg.target_wg=self
                wg.show()

    def __init__(self):
        super(InputO2M,self).__init__()
        self.relation=None
        self.maxh=8

    def set_vals(self,vals):
        self.obj_ids=vals.get(self.name,[])
        self.load_data()

    def get_val(self):
        val=[]
        for obj in self.objs:
            id=obj.get("id")
            if not id:
                val.append((0,0,obj))
            else:
                val.append((1,id,obj))
        return val

    def draw(self,win):
        super(InputO2M,self).draw(win)
        x=self.x+1
        win.addch(self.y,x,curses.ACS_RTEE)
        x+=1
        s=" "+self.string+" "
        win.addstr(self.y,self.x+2,s)
        x+=len(s)
        win.addch(self.y,x,curses.ACS_LTEE)

    def load_view(self):
        super(InputO2M,self).load_view()
        self.tree_mode.tree.seps=[[(0,False)],[(1,True)]]

class InputM2M(ObjList,Input):
    def __init__(self):
        super(InputM2M,self).__init__()
        self.maxh=8
        self.relation=None
        self.maxw=-1
        self.modes=["tree"]
        self.cur_mode="tree"

    def set_vals(self,vals): # XXX
        if self.name in vals:
            self.set_val(vals[self.name])

    def set_val(self,val,apply_on_change=True):
        super(InputM2M,self).set_val(val,apply_on_change)
        self.obj_ids=self.value
        self.load_data()

    def get_val(self):
        if not self.value:
            return False
        return [(6,0,self.value)]

    def load_view(self):
        super(InputM2M,self).load_view()
        self.tree_mode.tree.seps=[[(0,False)],[(1,True)]]

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
        self.draw(screen)
        screen.refresh()
        self.set_focus()

class PopupPanel(Panel):
    pass

class SearchPopup(Table):
    def __init__(self):
        super(SearchPopup,self).__init__()
        self.col=1
        self.title=Label()
        self.add(self.title)
        self.obj_list=ObjList()
        self.obj_list.commands=[]
        self.obj_list.can_focus=False
        self.obj_list.modes=["tree"]
        self.obj_list.cur_mode="tree"
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
        self.obj_list.tree.listeners["select"]=[]
        def on_select(line_no,source):
            obj=self.obj_list.objs[line_no]
            self.target_wg.set_val((obj["id"],obj["name"]))
            root_panel.close_popup(self)
        self.obj_list.tree.add_event_listener("select",on_select)
        self.title.string="Search: "+self.obj_list.tree.string
        self.string=self.obj_list.tree.string
        res=rpc_exec(self.model,"name_search",query)
        if len(res)==1:
            self.target_wg.set_val(res[0])
            self.target_wg.draw(screen)
            self.target_wg.set_cursor()
        else:
            self.obj_list.tree_mode.obj_ids=[r[0] for r in res]
            self.obj_list.load_data()
            root_panel.show_popup(self)

class LinkPopup(Table):
    def on_ok(self,arg,source):
        self.target_wg.objs.append(self.obj_list.form.get_vals())
        self.target_wg.tree.set_vals(self.target_wg.objs)
        root_panel.close_popup(self)

    def __init__(self):
        super(LinkPopup,self).__init__()
        self.col=1
        self.title=Label()
        self.add(self.title)
        self.obj_list=ObjList()
        self.obj_list.commands=[]
        self.obj_list.can_focus=False
        self.obj_list.modes=["form"]
        self.obj_list.cur_mode="form"
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
        self.obj_list.load_data()
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

class RootPanel(VerticalPanel):
    def __init__(self):
        super(RootPanel,self).__init__()
        self.windows=TabPanel()
        self.windows.maxh=-1
        self.add(self.windows)
        self.status=StatusPanel()
        self.status.maxh=1
        self.add(self.status)
        self.popups=DeckPanel()

    def new_window(self,act):
        if act["view_type"]=="tree":
            win=TreeWindow()
            win.model=act["res_model"]
            win.domain=act["domain"] and eval(act["domain"]) or []
            win.context=act["context"] and eval(act["context"]) or {}
            win.view_id=act["view_id"][0]
            win.name=act["name"]
            win.maxh=-1
            win.load_view()
            self.windows.add(win)
            win.load_data()
            self.windows.set_cur_wg(win)
            root_panel.compute()
            root_panel.draw()
            root_panel.refresh()
            root_panel.clear_focus()
            root_panel.set_focus()
            root_panel.set_cursor()
        elif act["view_type"]=="form":
            win=ListWindow()
            win.model=act["res_model"]
            domain=act["domain"] and eval(act["domain"]) or ""
            win.context=act["context"] and eval(act["context"]) or ""
            win.modes=act["view_mode"].split(",")
            win.cur_mode=win.modes[0]
            win.name=act["name"]
            win.maxh=-1
            win.load_view()
            win.obj_ids=rpc_exec(act["res_model"],"search",domain,0,10)
            self.windows.add(win)
            win.load_data()
            self.windows.set_cur_wg(win)
            root_panel.compute()
            root_panel.draw()
            root_panel.refresh()
            root_panel.clear_focus()
            root_panel.set_focus()
            root_panel.set_cursor()
        else:
            raise Exception("Unsupported view type: %s"%act["view_type"])

    def set_cursor(self):
        wg_f=self.get_focus()
        if wg_f:
            wg_f.set_cursor()

    def show_popup(self,wg):
        self.popups.add(wg)
        self.popups.cur_wg=wg
        self.main.cur_wg=self.popups

    def close_popup(self,wg):
        if wg!=self.popups.cur_wg:
            raise Exception("popup is not currently active")
        self.popups._childs.pop()
        if not self.popups._childs:
            self.main.cur_wg=self.windows

    def compute(self):
        super(RootPanel,self).compute(24,80,0,0)

    def draw(self):
        screen.clear()
        super(RootPanel,self).draw(screen)

    def refresh(self):
        screen.refresh()
        super(RootPanel,self).refresh(screen)

def view_to_s(el,d=0):
    s="  "*d+el.tag
    for k in sorted(el.attrib.keys()):
        v=el.attrib[k]
        s+=" %s=%s"%(k,v)
    for child in el:
        s+="\n"+view_to_s(child,d+1)
    return s

def act_window(act_id,_act=None):
    #log("act_window",act_id)
    if _act:
        act=_act
    else:
        act=rpc_exec("ir.actions.act_window","read",act_id,["name","res_model","domain","view_type","view_mode","view_id","context"])
    root_panel.new_window(act)

def action(act_id,_act=None):
    #log("action",act_id)
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
        wg_f=root_panel.get_focus()
        if not wg_f:
            raise Exception("could not find focused widget")
        root_panel.process_event("keypress",k,wg_f)
        if k in (ord("\t"),curses.KEY_DOWN):
            ind=root_panel.get_tabindex()
            i=ind.index(wg_f)
            i=(i+1)%len(ind)
            root_panel.clear_focus()
            ind[i].set_focus()
            root_panel.set_cursor()
        elif k==curses.KEY_UP:
            ind=root_panel.get_tabindex()
            i=ind.index(wg_f)
            i=(i-1)%len(ind)
            root_panel.clear_focus()
            ind[i].set_focus()
            root_panel.set_cursor()
curses.wrapper(start)
