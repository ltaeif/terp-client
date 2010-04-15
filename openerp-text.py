#!/usr/bin/python
##############################################################################
#
#    OpenERP-Text: Text-Mode Client for OpenERP
#    Copyright (C) 2010 David Janssens <david.j@almacom.co.th>
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
uid=opts.uid
passwd=opts.passwd

screen=None

def log(*args):
    msg=" ".join([str(a) for a in args])
    screen.addstr(msg+"\n")
    screen.refresh()

def rpc_exec(*args):
    try:
        return rpc.execute(dbname,uid,passwd,*args)
    except Exception,e:
        raise Exception("RPC failed: %s\n%s"%(str(args),str(e)))

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
        self.h=1
        self.maxw=-1
        self.borders=[0,0,0,0]
        self.align="left"
        self.cx=None
        self.cy=None
        self.colspan=1
        self.string=""
        self.states=None
        self.readonly=False
        self.invisible=False
        self.attrs={}
        self.can_focus=False

    def set_attrib(self,attrib):
        for k,v in attrib.items():
            if k=="string":
                self.string=v
                self.set_maxw()
            elif k=="colspan":
                self.colspan=int(v)
            elif k=="col":
                self.num_cols=int(v)
            elif k=="states":
                self.states=v.split(",")
            elif k=="readonly":
                self.readonly=True
            elif k=="attrs":
                self.attrs=eval(v)

    def set_vals(self,vals):
        for attr,dom in self.attrs.items():
            setattr(self,attr,eval_dom(dom,vals))
        if self.states:
            self.invisible=not vals["state"] in self.states

    def set_maxw(self):
        pass

    def to_s(self,d=0):
        s="  "*d
        s+=" "+self.__class__.__name__
        for name in dir(self):
            if name.startswith("_"):
                continue
            val=getattr(self,name)
            if callable(val):
                continue
            s+=" %s=%s"%(name,str(val))
        return s

    def draw(self,win):
        pass

    def get_focused(self):
        if not self.can_focus:
            return None
        return self

    def key_pressed(k):
        pass

class Panel(Widget):
    def __init__(self):
        super(Panel,self).__init__()
        self._childs=[]
        self._focused_wg=None

    def add(self,wg):
        self._childs.append(wg)
        if not self._focused_wg and wg.can_focus:
            self._focused_wg=wg

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

    def draw(self,win):
        for c in self._vis_childs():
            c.draw(win)

    def set_vals(self,vals):
        super(Panel,self).set_vals(vals)
        for c in self._childs:
            c.set_vals(vals)

    def get_focused(self):
        if not self._focused_wg:
            return self
        return self._focused_wg.get_focused()

class DeckPanel(Panel):
    def __init__(self):
        super(DeckPanel,self).__init__()
        self.cur_wg=None

    def add(self,wg):
        super(DeckPanel,self).add(wg)
        if self.cur_wg==None:
            self.cur_wg=wg

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

class Table(Panel):
    def __init__(self):
        super(Table,self).__init__()
        self.num_cols=4
        self.num_rows=0
        self._childs=[]
        self._child_cx=0
        self._child_cy=0
        self.seps=[0,1]
        self.h_top=None
        self.w_left=None

    def add(self,wg):
        if wg.colspan>self.num_cols:
            raise Exception("invalid colspan")
        if self._child_cx+wg.colspan>self.num_cols:
            self._child_cy+=1
            self._child_cx=0
        wg.cy=self._child_cy
        wg.cx=self._child_cx
        self._child_cx+=wg.colspan
        self._childs.append(wg)
        self.num_rows=wg.cy+1

    def newline(self):
        self._child_cy+=1
        self._child_cx=0

    def _compute_pass1(self):
        if not self._childs:
            return
        for widget in self._vis_childs():
            if hasattr(widget,"_compute_pass1"):
                widget._compute_pass1()
        # 1. compute container max width
        expand=False
        for wg in self._vis_childs():
            if wg.maxw==-1:
                expand=True
                break
        if expand:
            self.maxw=-1
        else:
            w_left=[0]
            for i in range(1,self.num_cols+1):
                w_max=w_left[i-1]
                for wg in self._vis_childs():
                    cr=wg.cx+wg.colspan
                    if cr!=i:
                        continue
                    w=w_left[wg.cx]+wg.maxw
                    if wg.cx>0:
                        w+=self.seps[1]
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
            h+=self.h_top[-1]
            if i>0:
                h+=self.seps[0]
            self.h_top.append(h)
        self.h=self.borders[0]+self.h_top[-1]+self.borders[2]

    def _compute_pass2(self):
        if not self._childs:
            self.w=0
            return
        # 1. compute child widths
        w_avail=self.w-self.borders[3]-self.borders[1]
        for wg in self._vis_childs():
            wg.w=0
        w_left=[0]*(self.num_cols+1)
        w_rest=w_avail
        # allocate space fairly to every child
        while w_rest>0:
            w_alloc=w_rest-self.seps[1]*(self.num_cols-1)
            if w_alloc>self.num_cols:
                dw=w_alloc/self.num_cols
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
                w=w_left[wg.cx]+wg.w
                if wg.cx>0:
                    w+=self.seps[1]
                cr=wg.cx+wg.colspan
                if w>w_left[cr]:
                    dwl=w-w_left[cr]
                    for i in range(cr,self.num_cols+1):
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
            w=w_left[wg.cx]+wg.w
            if wg.cx>0:
                w+=self.seps[1]
            cr=wg.cx+wg.colspan
            if w<w_left[cr]:
                dw=w_left[cr]-w
                if wg.maxw!=-1:
                    dw=min(dw,wg.maxw-wg.w)
                wg.w+=dw
        # 2. compute child positions
        for wg in self._vis_childs():
            wg.y=self.y+self.borders[0]+self.h_top[wg.cy]+(wg.cy>0 and self.seps[0] or 0)
            if wg.align=="right":
                wg.x=self.x+self.borders[3]+w_left[wg.cx+wg.colspan]-wg.w
            else:
                wg.x=self.x+self.borders[3]+w_left[wg.cx]+(wg.cx>0 and self.seps[1] or 0)
        for child in self._vis_childs():
            if hasattr(child,"_compute_pass2"):
                child._compute_pass2()

    def compute(self,w,y,x):
        self._compute_pass1()
        self.w=w
        self.y=y
        self.x=x
        self._compute_pass2()

class Form(Table):
    def __init__(self):
        super(Form,self).__init__()
        self.relation=None
        self.string=""

    def draw(self,win):
        curses.textpad.rectangle(win,self.y,self.x,self.y+self.h-1,self.x+self.w-1)
        super(Form,self).draw(win)

class Group(Table):
    def __init__(self):
        super(Group,self).__init__()
        self.string=""

class Notebook(DeckPanel):
    def __init__(self):
        super(Notebook,self).__init__()
        self.can_focus=True

    def draw(self,win):
        curses.textpad.rectangle(win,self.y,self.x,self.y+self.h-1,self.x+self.w-1)
        x=self.x+1
        i=0
        for wg in self._childs:
            if i==0:
                win.addch(self.y,x,curses.ACS_RTEE)
            else:
                win.addch(self.y,x,curses.ACS_VLINE)
            x+=1
            s=" "+wg.string+" "
            if self.cur_wg==wg:
                win.addstr(self.y,x,s,curses.A_BOLD)
            else:
                win.addstr(self.y,x,s)
            x+=len(s)
            i+=1
        win.addch(self.y,x,curses.ACS_LTEE)
        super(Notebook,self).draw(win)

class Page(Table):
    def __init__(self):
        super(Page,self).__init__()

class ListView(Widget):
    def __init__(self):
        super(ListView,self).__init__()
        self.relation=None
        self.headers=[]
        self.sep=1
        self.h=8
        self.borders=[1,1,1,1]

    def _compute_pass1(self):
        self.num_cols=len(self.headers)
        self.col_maxw=[]
        for name,string in self.headers:
            self.col_maxw.append(len(string))
        self.maxw=-1

    def _compute_pass2(self):
        self.col_w=[0]*self.num_cols
        w_avail=self.w-self.borders[3]-self.borders[1]
        w_rest=w_avail
        while w_rest>0:
            w_alloc=w_rest-self.sep*(self.num_cols-1)
            if w_alloc>self.num_cols:
                dw=w_alloc/self.num_cols
            else:
                dw=1
            incr=False
            for i in range(self.num_cols):
                maxw=self.col_maxw[i]
                if maxw!=-1:
                    colw=self.col_w[i]
                    if not colw<maxw:
                        continue
                    dw_=min(dw,maxw-colw)
                else:
                    dw_=dw
                self.col_w[i]+=dw_
                w_rest-=dw_
                incr=True
                if not w_rest:
                    break
            if not incr:
                break
        self.col_x=[self.x+self.borders[3]]
        for i in range(1,self.num_cols):
            self.col_x.append(self.col_x[i-1]+self.col_w[i-1]+self.sep)

    def draw(self,win):
        curses.textpad.rectangle(win,self.y,self.x,self.y+self.h-1,self.x+self.w-1)
        for i in range(1,self.num_cols):
            x=self.col_x[i]-1
            win.vline(self.y+1,x,curses.ACS_VLINE,self.h-2)
            win.addch(self.y,x,curses.ACS_TTEE)
            win.addch(self.y+self.h-1,x,curses.ACS_BTEE)
        for i in range(self.num_cols):
            name,string=self.headers[i]
            s=string[:self.col_w[i]]
            win.addstr(self.y+1,self.col_x[i],s)

class TreeView(Widget):
    def __init__(self):
        super(TreeView,self).__init__()
        self.relation=None
        self.headers=[]

class Label(Widget):
    def __init__(self):
        super(Label,self).__init__()

    def set_maxw(self):
        self.maxw=len(self.string)

    def draw(self,win):
        win.addstr(self.y,self.x,self.string)

class Separator(Widget):
    def __init__(self):
        super(Separator,self).__init__()
        self.string=""

    def draw(self,win):
        pass

class Button(Widget):
    def __init__(self):
        super(Button,self).__init__()

    def set_maxw(self):
        self.maxw=len(self.string)+2

    def draw(self,win):
        s="["+self.string[:self.w-2]+"]"
        win.addstr(self.y,self.x,s)

class FieldLabel(Widget):
    def __init__(self):
        super(FieldLabel,self).__init__()
        self.align="right"

    def set_maxw(self):
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

    def set_vals(self,vals):
        super(Input,self).set_vals(vals)
        if self.name in vals:
            self.value=vals[self.name]

class InputChar(Input):
    def __init__(self):
        super(InputChar,self).__init__()
        self.size=None
        self.value=""

    def draw(self,win):
        if self.value!=False:
            s=self.value[:self.w]
        else:
            s=""
        s+=" "*(self.w-len(s))
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

    def validate(self,val):
        return val

class InputInteger(Input):
    def __init__(self):
        super(InputInteger,self).__init__()
        self.maxw=9

    def draw(self,win):
        if self.value!=False:
            s=str(self.value)[:self.w]
        else:
            s=""
        s+=" "*(self.w-len(s))
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

class InputFloat(Input):
    def __init__(self):
        super(InputFloat,self).__init__()
        self.maxw=12

    def draw(self,win):
        if self.value!=False:
            s=str(self.value)[:self.w]
        else:
            s=""
        s+=" "*(self.w-len(s))
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

class InputSelect(Input):
    def __init__(self):
        super(InputSelect,self).__init__()
        self.selection=[]

    def set_selection(self,sel):
        self.selection=sel
        self.maxw=0
        for k,v in sel:
            self.maxw=max(self.maxw,len(v))

    def draw(self,win):
        if self.value!=False:
            s=None
            for k,v in self.selection:
                if k==self.value:
                    s=v
                    break
            if not s:
                raise Exception("invalid selection value: %s"%self.value)
            s=s[:self.w]
        else:
            s=""
        s+=" "*(self.w-len(s))
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

class InputText(Input):
    def __init__(self):
        super(InputText,self).__init__()
        self.height=5

    def draw(self,win):
        s=" "*self.w
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

class InputBoolean(Input):
    def __init__(self):
        super(InputBoolean,self).__init__()
        self.maxw=1

    def draw(self,win):
        s=(self.value and "Y" or "N")[:self.w]
        s+=" "*(self.w-len(s))
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

class InputDate(Input):
    def __init__(self):
        super(InputDate,self).__init__()
        self.maxw=10

    def draw(self,win):
        if self.value!=False:
            s=self.value[:self.w]
        else:
            s=""
        s+=" "*(self.w-len(s))
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

class InputDatetime(Input):
    def __init__(self):
        super(InputDatetime,self).__init__()
        self.maxw=19

    def draw(self,win):
        if self.value!=False:
            s=self.value[:self.w]
        else:
            s=""
        s+=" "*(self.w-len(s))
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

class InputM2O(Input):
    def __init__(self):
        super(InputM2O,self).__init__()
        self.relation=None

    def draw(self,win):
        if self.value!=False:
            s=self.value[1][:self.w]
        else:
            s=""
        s+=" "*(self.w-len(s))
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

class InputO2M(DeckPanel):
    def __init__(self):
        super(InputO2M,self).__init__()
        self.relation=None
        self.tree=None
        self.form=None

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

    def draw(self,win):
        pass

def create_widget(el,panel=None,fields=None):
    if el.tag=="form":
        wg=Form()
        wg.borders=[1,1,1,1]
        for child in el:
            create_widget(child,panel=wg,fields=fields)
        return wg
    elif el.tag=="tree":
        wg=ListView()
        for child in el:
            name=child.attrib["name"]
            field=fields[name]
            wg.headers.append((name,field["string"]))
        return wg
    elif el.tag=="label":
        wg=Label()
        wg.set_attrib(el.attrib)
        panel.add(wg)
        return wg
    elif el.tag=="newline":
        panel.newline()
        return None
    elif el.tag=="separator":
        wg=Separator()
        wg.set_attrib(el.attrib)
        panel.add(wg)
        return wg
    elif el.tag=="button":
        wg=Button()
        wg.set_attrib(el.attrib)
        panel.add(wg)
        return wg
    elif el.tag=="field":
        field=fields[el.attrib["name"]]
        attrib={"string": field["string"]}
        attrib.update(el.attrib)
        if not el.attrib.get("nolabel"):
            wg_l=FieldLabel()
            wg_l.set_attrib(attrib)
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
            wg.set_selection(field["selection"])
        elif field["type"]=="many2one":
            wg=InputM2O()
        elif field["type"]=="one2many":
            wg=InputO2M()
            tree_view=field["views"].get("tree")
            if not tree_view:
                tree_view=rpc_exec(field["relation"],"fields_view_get",False,"tree",{})
            tree_arch=xml.etree.ElementTree.fromstring(tree_view["arch"])
            wg_t=create_widget(tree_arch,fields=tree_view["fields"])
            wg_t.relation=field["relation"]
            wg.add(wg_t,"tree")
            form_view=field["views"].get("form")
            if not form_view:
                form_view=rpc_exec(field["relation"],"fields_view_get",False,"form",{})
            form_arch=xml.etree.ElementTree.fromstring(form_view["arch"])
            wg_f=create_widget(form_arch,fields=form_view["fields"])
            wg_f.relation=field["relation"]
            wg.add(wg_f,"form")
        elif field["type"]=="many2many":
            wg=InputM2M()
            tree_view=field["views"].get("tree")
            if not tree_view:
                tree_view=rpc_exec(field["relation"],"fields_view_get",False,"tree",{})
            tree_arch=xml.etree.ElementTree.fromstring(tree_view["arch"])
            wg_t=create_widget(tree_arch,fields=tree_view["fields"])
            wg_t.relation=field["relation"]
            wg.add(wg_t)
        else:
            raise Exception("unsupported field type: %s"%field["type"])
        wg.name=el.attrib["name"]
        wg.set_attrib(attrib)
        panel.add(wg)
        return wg
    elif el.tag=="group":
        wg=Group()
        wg.set_attrib(el.attrib)
        for child in el:
            create_widget(child,wg,fields=fields)
        panel.add(wg)
        return wg
    elif el.tag=="notebook":
        wg=Notebook()
        wg.set_attrib(el.attrib)
        wg.borders=[1,1,1,1]
        for elp in el:
            wg_p=Page()
            wg_p.set_attrib(elp.attrib)
            wg.add(wg_p)
            for child in elp:
                create_widget(child,wg_p,fields=fields)
        panel.add(wg)
        return wg
    else:
        raise Exception("invalid tag: "+el.tag)

def view_to_s(el,d=0):
    s="  "*d+el.tag
    for k in sorted(el.attrib.keys()):
        v=el.attrib[k]
        s+=" %s=%s"%(k,v)
    for child in el:
        s+="\n"+view_to_s(child,d+1)
    return s

def act_window_tree(act):
    #log("act_window_tree",act)
    model=act["res_model"]
    domain=act["domain"] and eval(act["domain"]) or []
    context=act["context"] and eval(act["context"]) or {}
    view=rpc_exec(model,"fields_view_get",act["view_id"][0],"tree",context)
    #log("view",view)
    ids=rpc_exec(model,"search",domain)
    objs_l=rpc_exec(model,"read",ids,["id","name"])
    screen.addstr(0,0,"1 "+act["name"])
    screen.chgat(0,0,7,curses.A_REVERSE)
    win=screen.subwin(23,80,1,0)
    win.clear()
    win.box()
    win.vline(1,25,curses.ACS_VLINE,21)
    win.addch(0,25,curses.ACS_TTEE)
    win.addch(22,25,curses.ACS_BTEE)
    win.hline(2,26,curses.ACS_HLINE,78)
    win.addch(2,25,curses.ACS_LTEE)
    win.addch(2,79,curses.ACS_RTEE)
    win_l=win.subwin(21,24,2,1)
    win_r=win.subwin(19,53,4,26)
    pad_r=curses.newpad(100,53)
    y=0
    for obj in objs_l:
        win_l.addstr(y,1,obj["name"])
        y+=1
    fields=view["fields"]
    field_names=fields.keys()
    field_parent=view["field_parent"]
    win.addstr(1,27,fields[field_names[0]]["string"])
    if objs_l:
        child_ids=rpc_exec(model,"read",objs_l[0]["id"],[field_parent])[field_parent]
        objs_r=rpc_exec(model,"read",child_ids,["id",field_parent]+field_names)
        y=0
        for obj in objs_r:
            obj["_depth"]=0
            obj["_expanded"]=False
            pad_r.addstr(y,1,obj["name"])
            if obj[field_parent]:
                pad_r.addch(y,0,"/")
            y+=1
    select_l=0
    win_l.chgat(select_l,0,24,curses.A_REVERSE)
    screen.refresh()
    pad_r.refresh(0,0,4,26,22,78)
    screen.move(2,2)
    mode="l"
    scroll_r=0
    while 1:
        c=screen.getch()
        if c==curses.KEY_DOWN:
            if mode=="l":
                i=screen.getyx()[0]-2
                i+=1
                if i>=len(objs_l):
                    i=0
                screen.move(i+2,2)
            elif mode=="r":
                i=screen.getyx()[0]-4+scroll_r
                i+=1
                if i>=len(objs_r):
                    i=0
                obj=objs_r[i]
                scroll=False
                if i-scroll_r>18:
                    scroll_r=i-18
                    scroll=True
                elif i<scroll_r:
                    scroll_r=i
                    scroll=True
                if scroll:
                    pad_r.refresh(scroll_r,0,4,26,22,79)
                screen.move(4+i-scroll_r,27+obj["_depth"]*2)
        elif c==curses.KEY_UP:
            if mode=="l":
                i=screen.getyx()[0]-2
                i-=1
                if i<0:
                    i=len(objs_l)-1
                screen.move(i+2,2)
            elif mode=="r":
                i=screen.getyx()[0]-4+scroll_r
                i-=1
                if i<0:
                    i=len(objs_r)-1
                obj=objs_r[i]
                scroll=False
                if i-scroll_r>18:
                    scroll_r=i-18
                    scroll=True
                elif i<scroll_r:
                    scroll_r=i
                    scroll=True
                if scroll:
                    pad_r.refresh(scroll_r,0,4,26,22,79)
                screen.move(i+4-scroll_r,27+obj["_depth"]*2)
        elif c==curses.KEY_RIGHT:
            if mode=="l":
                mode="r"
                screen.move(4,27)
            elif mode=="r":
                y,x=screen.getyx()
                i=y-4
                obj=objs_r[i]
                if obj["_expanded"]:
                    continue
                child_ids=rpc_exec(model,"read",obj["id"],[field_parent])[field_parent]
                if child_ids:
                    childs=rpc_exec(model,"read",child_ids,["id",field_parent]+field_names)
                    childs.reverse()
                    for child in childs:
                        child["_depth"]=obj["_depth"]+1
                        child["_expanded"]=False
                        objs_r.insert(i+1,child)
                        pad_r.move(i+1,0)
                        pad_r.insertln()
                        pad_r.addstr(i+1,1+child["_depth"]*2,child["name"])
                        if child[field_parent]:
                            pad_r.addch(i+1,child["_depth"]*2,"/")
                    obj["_expanded"]=True
                pad_r.refresh(0,0,4,26,22,79)
                screen.move(y,x)
        elif c==curses.KEY_LEFT:
            if mode=="r":
                i=screen.getyx()[0]-4+scroll_r
                obj=objs_r[i]
                if obj["_depth"]==0 and not obj["_expanded"]:
                    mode="l"
                    screen.move(2+select_l,2)
                    win_l.refresh()
                    continue
                while not obj["_expanded"]:
                    i-=1
                    obj=objs_r[i]
                child_ids=obj[field_parent]
                while i+1<len(objs_r):
                    child=objs_r[i+1]
                    if child["id"] not in child_ids:
                        break
                    child_ids+=child[field_parent]
                    objs_r.pop(i+1)
                    pad_r.move(i+1,0)
                    pad_r.deleteln()
                    folded=True
                pad_r.refresh(0,0,4,26,22,79)
                screen.move(i+4,27+obj["_depth"]*2)
                obj["_expanded"]=False
        elif c==ord("\t"):
            if mode=="l":
                mode="r"
                screen.move(4,27)
            elif mode=="r":
                mode="l"
                screen.move(2+select_l,2)
        elif c==ord("\n"):
            if mode=="l":
                y,x=screen.getyx()
                win_l.chgat(select_l,0,24,0)
                select_l=y-2
                win_l.chgat(select_l,0,24,curses.A_REVERSE)
                win_l.refresh()

                pad_r.clear()
                child_ids=rpc_exec(model,"read",objs_l[select_l]["id"],[field_parent])[field_parent]
                objs_r=rpc_exec(model,"read",child_ids,["id",field_parent]+field_names)
                i=0
                for obj in objs_r:
                    obj["_depth"]=0
                    obj["_expanded"]=False
                    pad_r.addstr(i,1,obj["name"])
                    if obj[field_parent]:
                        pad_r.addch(i,0,"/")
                    i+=1
                pad_r.refresh(0,0,4,26,22,78)
                screen.move(y,x)
            elif mode=="r":
                i=screen.getyx()[0]-4+scroll_r
                obj=objs_r[i]
                res=rpc_exec("ir.values","get","action","tree_but_open",[(model,obj["id"])])
                if not res:
                    continue
                act=res[0][2]
                action(act["id"])

def act_window_form(act):
    model=act["res_model"]
    view_modes=act["view_mode"].split(",")
    mode=view_modes[0]
    domain=act["domain"] and eval(act["domain"]) or []
    context=act["context"] and eval(act["context"]) or {}
    view_id=False
    view=rpc_exec(model,"fields_view_get",view_id,mode,context)
    fields=view["fields"]
    field_names=fields.keys()
    arch=xml.etree.ElementTree.fromstring(view["arch"])
    screen.clear()
    screen.addstr("1 Menu ")
    screen.addstr("2 "+act["name"]+" ",curses.A_REVERSE)
    pad=curses.newpad(100,80)
    if mode=="tree":
        ids=rpc_exec(model,"search",domain)
        objs=rpc_exec(model,"read",ids,["id"]+field_names)
    elif mode=="form":
        obj={}
        defaults=rpc_exec(model,"default_get",field_names)
        for name,val in defaults.items():
            if fields[name]["type"]=="many2one" and type(val)==type(1):
                val=rpc_exec(fields[name]["relation"],"name_get",[val])[0]
            obj[name]=val
        form=create_widget(arch,fields=fields)
        form.set_vals(obj)
        form.compute(80,1,0)
        form.draw(screen)
        wg=form.get_focused()
        screen.move(wg.y,wg.x)
        screen.refresh()
    else:
        raise Exception("view mode not implemented: "+mode)
    while 1:
        c=screen.getch()
        if c==curses.KEY_DOWN:
            y,x=screen.getyx()
            i=y-4
            i+=1
            if i>len(objs)-1:
                i=0
            screen.move(4+i,1)
        elif c==curses.KEY_UP:
            y,x=screen.getyx()
            i=y-4
            i-=1
            if i<0:
                i=len(objs)-1
            screen.move(4+i,1)
        elif c==ord(" "):
            y,x=screen.getyx()
            i=y-4
            obj=objs[i]
            if not obj.get("_selected"):
                x=1
                for name in headers:
                    screen.chgat(y,x,colw[name],curses.A_REVERSE)
                    x+=colw[name]+1
                obj["_selected"]=True
            else:
                x=1
                for name in headers:
                    screen.chgat(y,x,colw[name],0)
                    x+=colw[name]+1
                obj["_selected"]=False
            screen.refresh()
        elif c==ord("\n"):
            pass

def act_window(act_id):
    #log("act_window",act_id)
    act=rpc_exec("ir.actions.act_window","read",act_id,["name","res_model","domain","view_type","view_mode","view_id","context"])
    if act["view_type"]=="tree":
        act_window_tree(act)
    elif act["view_type"]=="form":
        act_window_form(act)
    else:
        raise Exception("Unsupported view type: %s"%act["view_type"])

def action(act_id):
    #log("action",act_id)
    act=rpc_exec("ir.actions.actions","read",act_id,["name","type"])
    if act["type"]=="ir.actions.act_window":
        act_window(act_id)
    else:
        raise Exception("Unsupported action type: %s"%act["type"])

def start(stdscr):
    global screen
    screen=stdscr
    screen.keypad(1)
    #curses.init_pair(1,curses.COLOR_RED,curses.COLOR_BLACK)
    user=rpc_exec("res.users","read",uid,["name","action_id","menu_id"])
    action(user["action_id"][0])
curses.wrapper(start)
