#!/usr/bin/python
##############################################################################
#
#    OpenERP-Text: Text-Mode Client for OpenERP
#    Copyright (C) 2010 Almacom (Thailand) Ltd.
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
tab_panel=None
dbg_flag=False

def log(*args):
    msg=" ".join([str(a) for a in args])
    screen.addstr(msg+"\n")
    screen.refresh()

def rpc_exec(*args):
    try:
        return rpc.execute(dbname,uid,passwd,*args)
    except Exception,e:
        raise Exception("RPC failed: %s %s %s %s\n%s"%(dbname,uid,passwd,str(args),str(e)))

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
    def __init__(self):
        self.x=None
        self.y=None
        self.w=None
        self.h=None
        self.maxw=None
        self.borders=[0,0,0,0]
        self.align="left"
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
        self.string=""
        self.readonly=False
        self.invisible=False
        self.states=None
        self.listeners={
            "keypress": [],
        }

    def set_field_attrs(self,attrs):
        for k,v in attrs.items():
            if k in ("string","readonly","states","size","select","required","domain","relation","context","digits","change_default","help","selection"):
                self.field_attrs[k]=v
            elif k in ("views","type"):
                pass
            else:
                raise Exception("unsupported field attribute: %s"%k)
        for k,v in self.field_attrs.items():
            setattr(self,k,v)

    def set_view_attrs(self,attrs):
        for k,v in attrs.items():
            if k in ("string","name","on_change","domain","context","type","widget","mode","sum","icon","default_get"):
                val=v
            elif k in ("colspan","col"):
                val=int(v)
            elif k in ("readonly","select","required","nolabel","invisible"):
                val=eval(v) and True or False
            elif k=="states":
                val=v.split(",")
            elif k=="attrs":
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
            if not name in ("x","y","maxw","h","w","string","col","colspan","value","can_focus","has_focus"):
                continue
            val=getattr(self,name)
            if callable(val):
                continue
            s+=" %s=%s"%(name,str(val))
        return s

    def draw(self,win):
        raise Exception("method not implemented")

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
        self.has_focus=False

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

    def compute(self,w,y,x):
        self._compute_pass1()
        self.w=w
        self.y=y
        self.x=x
        self._compute_pass2()

    def draw(self,win):
        for c in self._vis_childs():
            c.draw(win)

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

class DeckPanel(Panel):
    def on_keypress(self,k,source):
        if k==curses.KEY_RIGHT:
            if source==self:
                i=self._childs.index(self.cur_wg)
                i=(i+1)%len(self._childs)
                self.cur_wg=self._childs[i]
                refresh_screen()
                update_cursor()
        elif k==curses.KEY_LEFT:
            if source==self:
                i=self._childs.index(self.cur_wg)
                i=(i-1)%len(self._childs)
                self.cur_wg=self._childs[i]
                refresh_screen()
                update_cursor()

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
        maxws=[wg.maxw for wg in self._vis_childs()]
        if -1 in maxws:
            self.maxw=-1
        else:
            self.maxw=max(maxws)+self.borders[1]+self.borders[3]
        self.h=max([wg.h for wg in self._vis_childs()])+self.borders[0]+self.borders[2]

    def _compute_pass2(self):
        w=self.w-self.borders[1]-self.borders[3]
        for wg in self._vis_childs():
            if wg.maxw==-1:
                wg.w=w
            else:
                wg.w=min(w,wg.maxw)
            wg.y=self.y+self.borders[0]
            wg.x=self.x+self.borders[3]
        for wg in self._vis_childs():
            if hasattr(wg,"_compute_pass2"):
                wg._compute_pass2()

    def draw(self,win):
        if not self.cur_wg:
            return
        self.cur_wg.draw(win)

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
        self.borders=[1,0,0,0]
        self.can_focus=True
        def on_keypress(k,source):
            if k==ord('c'):
                if source==self:
                    self.remove(self.cur_wg)
                    refresh_screen()
                    update_cursor()
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
        curses.textpad.rectangle(win,self.y,self.x,self.y+self.h-1,self.x+self.w-1)
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
        super(Notebook,self).draw(win)

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
        if wg.colspan>self.col:
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
        if self.maxw==None:
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
        # 2. compute container height
        self.h_top=[0]
        for i in range(self.num_rows):
            h=0
            for wg in self._vis_childs():
                if wg.cy!=i:
                    continue
                if wg.h>h:
                    h=wg.h
            h+=self.h_top[-1]+self._get_sep_size("y",i)
            self.h_top.append(h)
        if self.h==None:
            self.h=self.borders[0]+self.h_top[-1]+self.borders[2]

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
        # 2. compute child positions
        for wg in self._vis_childs():
            wg.y=self.y+self.borders[0]+self.h_top[wg.cy]+self._get_sep_size("y",wg.cy)
            if wg.align=="right":
                wg.x=self.x+self.borders[3]+w_left[wg.cx+wg.colspan]-wg.w
            else:
                wg.x=self.x+self.borders[3]+w_left[wg.cx]+self._get_sep_size("x",wg.cx)
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
        self.seps=[[(0,False)],[(1,False)]]
        self.col=4

    def draw(self,win):
        super(Form,self).draw(win)
        win.addch(self.y,self.x+self.w-6,curses.ACS_RTEE)
        win.addstr(self.y,self.x+self.w-5,"L")
        win.addch(self.y,self.x+self.w-4,curses.ACS_VLINE)
        win.addstr(self.y,self.x+self.w-3,"F")
        win.addch(self.y,self.x+self.w-2,curses.ACS_LTEE)

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

class ListView(Table):
    def on_select(self,line_no):
        self.selected=[line_no]
        self.process_event("select",line_no,self)

    def on_keypress(self,k,source):
        if k==ord("\n"):
            if source in self._childs:
                i=self._childs.index(source)
                line_no=i/self.col
                self.on_select(line_no)

    def __init__(self):
        super(ListView,self).__init__()
        self.relation=None
        self.h=8
        self.borders=[1,1,1,1]
        self.seps=[[(0,False)],[(1,True)]]
        self.selected=[]
        self.lines=[]
        self.num_lines=0
        self.has_header=True
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
        win.addch(self.y,self.x+self.w-6,curses.ACS_RTEE)
        win.addstr(self.y,self.x+self.w-5,"L")
        win.addch(self.y,self.x+self.w-4,curses.ACS_VLINE)
        win.addstr(self.y,self.x+self.w-3,"F")
        win.addch(self.y,self.x+self.w-2,curses.ACS_LTEE)
        x=self.x+self.borders[3]
        w=self.w-self.borders[1]-self.borders[3]
        for sel in self.selected:
            wg=self._childs[sel*self.col]
            y=wg.y
            win.chgat(y,x,w,curses.A_BOLD)

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
                    refresh_screen()
                    update_cursor()
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
                    refresh_screen()
                    update_cursor()
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
        self.h=1

    def _compute_pass1(self):
        self.maxw=len(self.string)

    def draw(self,win):
        s=self.string[:self.w]
        win.addstr(self.y,self.x,s)

class Separator(Widget):
    def __init__(self):
        super(Separator,self).__init__()
        self.string=""
        self.h=1
        self.maxw=-1

    def draw(self,win):
        s=" "
        if self.string:
            s+=self.string[:self.w-1]
        s+=" "*(self.w-len(s))
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

class Button(Widget):
    def __init__(self):
        super(Button,self).__init__()
        self.can_focus=True
        self.h=1

    def _compute_pass1(self):
        self.maxw=len(self.string)+2

    def draw(self,win):
        s="["+self.string[:self.w-2]+"]"
        win.addstr(self.y,self.x,s)

    def set_cursor(self):
        screen.move(self.y,self.x+1)

class FieldLabel(Widget):
    def __init__(self):
        super(FieldLabel,self).__init__()
        self.align="right"
        self.h=1

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
        self.value=False
        self.can_focus=True
        self.h=1
        self.under=True

    def to_string(self):
        if self.value is False:
            return ""
        return str(self.value)

    def draw(self,win):
        s=self.to_string()[:self.w]
        s+=" "*(self.w-len(s))
        win.addstr(self.y,self.x,s,self.under and curses.A_UNDERLINE or 0)

    def _compute_pass1(self):
        if self.readonly:
            self.maxw=len(self.to_string())
        else:
            self.maxw=-1

    def set_vals(self,vals):
        super(Input,self).set_vals(vals)
        if self.name in vals:
            self.value=vals[self.name]

class InputChar(Input):
    pass

class InputInteger(Input):
    pass

class InputFloat(Input):
    pass

class InputSelect(Input):
    def __init__(self):
        super(InputSelect,self).__init__()
        self.selection=[]

    def to_string(self):
        if self.value is False:
            return ""
        for k,v in self.selection:
            if k==self.value:
                return v
        raise Exception("invalid selection value: %s"%self.value)

class InputText(Input):
    def __init__(self):
        super(InputText,self).__init__()
        self.h=7
        self.maxw=-1

    def draw(self,win):
        curses.textpad.rectangle(win,self.y,self.x,self.y+self.h-1,self.x+self.w-1)

    def set_cursor(self):
        screen.move(self.y+1,self.x+1)

class InputBoolean(Input):
    def to_string(self):
        return self.value and "Y" or "N"

class InputDate(Input):
    pass

class InputDatetime(Input):
    pass

class InputM2O(Input):
    def to_string(self):
        return self.value and self.value[1] or ""

class InputO2M(DeckPanel):
    def __init__(self):
        super(InputO2M,self).__init__()
        self.relation=None
        self.tree=None
        self.form=None
        self.maxw=-1
        self.can_focus=True

    def set_cursor(self):
        screen.move(self.y+2,self.x+1)

    def add(self,wg,type="tree"):
        super(InputO2M,self).add(wg)
        if type=="tree":
            self.tree=wg
        elif type=="form":
            self.form=wg
        else:
            raise Exception("Unsupported view type: %s"%type)

    def _compute_pass1(self):
        super(InputO2M,self)._compute_pass1()
        self.h=self.tree.h

class InputM2M(Panel):
    def __init__(self):
        super(InputM2M,self).__init__()
        self.h=8
        self.relation=None
        self.maxw=-1

    def draw(self,win):
        curses.textpad.rectangle(win,self.y,self.x,self.y+self.h-1,self.x+self.w-1)

class TreeWindow(HorizontalPanel):
    def __init__(self,act):
        super(TreeWindow,self).__init__()
        self.model=act["res_model"]
        self.domain=act["domain"] and eval(act["domain"]) or []
        self.context=act["context"] and eval(act["context"]) or {}
        self.view_id=act["view_id"][0]
        self.name=act["name"]
        self.field_parent=None
        self.root_list=ListView()
        self.root_list.col=1
        self.root_list.names=["name"]
        self.root_list.h=23
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
            tab_panel.clear_focus()
            self.tree.set_focus()
            refresh_screen()
            update_cursor()
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
                        wg.value=vals[name]
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
        self.tree.h=23
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

class FormWindow(DeckPanel):
    def __init__(self,act):
        super(FormWindow,self).__init__()
        self.model=act["res_model"]
        self.domain=act["domain"] and eval(act["domain"]) or []
        self.context=act["context"] and eval(act["context"]) or {}
        self.modes=act["view_mode"].split(",")
        self.name=act["name"]
        self.mode=self.modes[0]
        self.view={}
        self.fields={}

    def parse_tree(self,el,fields):
        if el.tag=="tree":
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
            wg.h=23
            wg.seps=[[(1,True),(0,False)],[(1,True)]]
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
                        wg.value=vals[name]
                    elif child.tag=="button":
                        wg=Button()
                    wg.can_focus=i==0
                    line.append(wg)
                    i+=1
                return line
            wg.make_line=make_line
        return wg

    def parse_form(self,el,fields=None,panel=None):
        if el.tag=="form":
            wg=Form()
            wg.borders=[1,1,1,1]
            for child in el:
                self.parse_form(child,panel=wg,fields=fields)
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
                        wg.value=vals[name]
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
            wg=Button()
            wg.set_view_attrs(el.attrib)
            panel.add(wg)
            return wg
        elif el.tag=="field":
            field=fields[el.attrib["name"]]
            if not el.attrib.get("nolabel"):
                wg_l=FieldLabel()
                wg_l.set_field_attrs(field)
                wg_l.set_view_attrs(el.attrib)
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
                tree_view=field["views"].get("tree")
                if not tree_view:
                    tree_view=rpc_exec(field["relation"],"fields_view_get",False,"tree",{})
                tree_arch=xml.etree.ElementTree.fromstring(tree_view["arch"])
                wg_t=self.parse_form(tree_arch,fields=tree_view["fields"])
                wg_t.relation=field["relation"]
                wg.add(wg_t,"tree")
                form_view=field["views"].get("form")
                if not form_view:
                    form_view=rpc_exec(field["relation"],"fields_view_get",False,"form",{})
                form_arch=xml.etree.ElementTree.fromstring(form_view["arch"])
                wg_f=self.parse_form(form_arch,fields=form_view["fields"])
                wg_f.relation=field["relation"]
                wg.add(wg_f,"form")
            elif field["type"]=="many2many":
                wg=InputM2M()
                tree_view=field["views"].get("tree")
                if not tree_view:
                    tree_view=rpc_exec(field["relation"],"fields_view_get",False,"tree",{})
                tree_arch=xml.etree.ElementTree.fromstring(tree_view["arch"])
                wg_t=self.parse_form(tree_arch,fields=tree_view["fields"])
                wg_t.relation=field["relation"]
                wg.add(wg_t)
            else:
                raise Exception("unsupported field type: %s"%field["type"])
            wg.name=el.attrib["name"]
            wg.set_field_attrs(field)
            wg.set_view_attrs(el.attrib)
            panel.add(wg)
            return wg
        elif el.tag=="group":
            wg=Group()
            wg.set_view_attrs(el.attrib)
            for child in el:
                self.parse_form(child,fields=fields,panel=wg)
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
                    self.parse_form(child,fields=fields,panel=wg_p)
            panel.add(wg)
            return wg
        else:
            raise Exception("invalid tag: "+el.tag)

    def load_view(self):
        if self.mode=="tree":
            view=rpc_exec(self.model,"fields_view_get",False,"tree",self.context)
            self.view["tree"]=view
            self.fields["tree"]=view["fields"]
            arch=xml.etree.ElementTree.fromstring(view["arch"])
            self.tree=self.parse_tree(arch,view["fields"])
            self.add(self.tree)
        elif self.mode=="form":
            view=rpc_exec(self.model,"fields_view_get",False,"form",self.context)
            self.view["form"]=view
            self.fields["form"]=view["fields"]
            arch=xml.etree.ElementTree.fromstring(view["arch"])
            self.form=self.parse_form(arch,view["fields"])
            self.add(self.form)

    def load_data(self):
        if self.mode=="tree":
            offset=0
            limit=20
            self.obj_ids=rpc_exec(self.model,"search",self.domain,offset,limit)
            self.objs=rpc_exec(self.model,"read",self.obj_ids,self.fields["tree"].keys())
            self.tree.add_lines(self.objs)
        elif self.mode=="form":
            #self.obj=rpc_exec(self.model,"read",[self.obj_id],self.fields["form"].keys())[0]
            self.obj=rpc_exec(self.model,"default_get",self.fields["form"].keys())
            for name,val in self.obj.items():
                if val==False:
                    continue
                field=self.fields["form"][name]
                if field["type"]=="many2one":
                    val_=rpc_exec(field["relation"],"name_get",[val])[0]
                    self.obj[name]=val_
            self.form.set_vals(self.obj)

def view_to_s(el,d=0):
    s="  "*d+el.tag
    for k in sorted(el.attrib.keys()):
        v=el.attrib[k]
        s+=" %s=%s"%(k,v)
    for child in el:
        s+="\n"+view_to_s(child,d+1)
    return s

def refresh_screen():
    tab_panel.compute(80,0,0)
    screen.clear()
    tab_panel.draw(screen)
    screen.refresh()

def update_cursor():
    wg_f=tab_panel.get_focus()
    if wg_f:
        wg_f.set_cursor()

def act_window_tree(act):
    win=TreeWindow(act)
    win.load_view()
    win.load_data()
    tab_panel.add(win)
    tab_panel.set_cur_wg(win)
    tab_panel.clear_focus()
    tab_panel.set_focus()
    refresh_screen()
    update_cursor()

def act_window_form(act):
    win=FormWindow(act)
    win.load_view()
    win.load_data()
    tab_panel.add(win)
    tab_panel.set_cur_wg(win)
    tab_panel.clear_focus()
    tab_panel.set_focus()
    refresh_screen()
    update_cursor()

def act_window(act_id,_act=None):
    #log("act_window",act_id)
    if _act:
        act=_act
    else:
        act=rpc_exec("ir.actions.act_window","read",act_id,["name","res_model","domain","view_type","view_mode","view_id","context"])
    if act["view_type"]=="tree":
        act_window_tree(act)
    elif act["view_type"]=="form":
        act_window_form(act)
    else:
        raise Exception("Unsupported view type: %s"%act["view_type"])

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
    global screen,tab_panel
    screen=stdscr
    screen.keypad(1)
    tab_panel=TabPanel()
    user=rpc_exec("res.users","read",uid,["name","action_id","menu_id"])
    action(user["action_id"][0])
    while 1:
        k=screen.getch()
        if k==ord("d"):
            global dbg_flag
            dbg_flag^=1
        wg_f=tab_panel.get_focus()
        if dbg_flag:
            set_trace()
        if not wg_f:
            raise Exception("could not find focused widget")
        tab_panel.process_event("keypress",k,wg_f)
        if k in (ord("\t"),curses.KEY_DOWN):
            ind=tab_panel.get_tabindex()
            i=ind.index(wg_f)
            i=(i+1)%len(ind)
            tab_panel.clear_focus()
            ind[i].set_focus()
            update_cursor()
        elif k==curses.KEY_UP:
            ind=tab_panel.get_tabindex()
            i=ind.index(wg_f)
            i=(i-1)%len(ind)
            tab_panel.clear_focus()
            ind[i].set_focus()
            update_cursor()
curses.wrapper(start)
