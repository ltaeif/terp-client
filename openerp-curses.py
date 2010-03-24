#!/usr/bin/python
##############################################################################
#
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

import curses
import curses.textpad
import curses.panel
import sys
import time
import xmlrpclib

try:
    host=sys.argv[1]
    dbname=sys.argv[2]
    uid=int(sys.argv[3])
    passwd=sys.argv[4]
except:
    raise Exception("Usage: %s HOST DBNAME UID PASSWD"%sys.argv[0])

port=8069
rpc=xmlrpclib.ServerProxy("http://%s:%d/xmlrpc/object"%(host,port))

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

def act_window_tree(act):
    #log("act_window_tree",act)
    domain=act["domain"] and eval(act["domain"]) or {}
    context=act["context"] and eval(act["context"]) or {}
    view=rpc_exec(act["res_model"],"fields_view_get",act["view_id"][0],"tree",context)
    #log("view",view)
    ids=rpc_exec(act["res_model"],"search",domain)
    objs_l=rpc_exec(act["res_model"],"read",ids,["id","name"])
    screen.addstr(0,0,"1 "+act["name"])
    screen.addstr(0,8,"2 Products  3 Purchase orders")
    screen.chgat(0,0,7,curses.A_REVERSE)
    win=screen.subwin(23,80,1,0)
    win.box()
    win.vline(1,25,curses.ACS_VLINE,21)
    win.addch(0,25,curses.ACS_TTEE)
    win.addch(22,25,curses.ACS_BTEE)
    win.hline(2,26,curses.ACS_HLINE,78)
    win.addch(2,25,curses.ACS_LTEE)
    win.addch(2,79,curses.ACS_RTEE)
    win_l=win.subwin(21,24,2,1)
    #win_l.box()
    win_r=win.subwin(19,53,4,26)
    #win_r.box()
    y=0
    for obj in objs_l:
        win_l.addstr(y,1,obj["name"],curses.A_BOLD)
        y+=1
    fields=view["fields"]
    field_names=fields.keys()
    field_parent=view["field_parent"]
    win.addstr(1,27,fields[field_names[0]]["string"])
    if objs_l:
        child_ids=rpc_exec(act["res_model"],"read",objs_l[0]["id"],[field_parent])[field_parent]
        objs_r=rpc_exec(act["res_model"],"read",child_ids,["id",field_parent]+field_names)
        y=0
        for obj in objs_r:
            obj["_depth"]=0
            obj["_expanded"]=False
            win_r.addstr(y,1,obj["name"],curses.A_BOLD)
            if obj[field_parent]:
                win_r.addch(y,0,"/")
            y+=1

    select_l=0
    win_l.chgat(select_l,0,24,curses.A_REVERSE|curses.A_BOLD)
    screen.move(2+select_l,2)
    screen.refresh()
    mode="l"
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
                i=screen.getyx()[0]-4
                i+=1
                if i>=len(objs_r):
                    i=0
                obj=objs_r[i]
                screen.move(i+4,27+obj["_depth"]*2)
        elif c==curses.KEY_UP:
            if mode=="l":
                i=screen.getyx()[0]-2
                i-=1
                if i<0:
                    i=len(objs_l)-1
                screen.move(i+2,2)
            elif mode=="r":
                i=screen.getyx()[0]-4
                i-=1
                if i<0:
                    i=len(objs_r)-1
                obj=objs_r[i]
                screen.move(i+4,27+obj["_depth"]*2)
        elif c==curses.KEY_RIGHT:
            if mode=="l":
                mode="r"
                screen.move(4,27)
            elif mode=="r":
                i=screen.getyx()[0]-4
                obj=objs_r[i]
                if obj["_expanded"]:
                    continue
                child_ids=rpc_exec(act["res_model"],"read",obj["id"],[field_parent])[field_parent]
                if child_ids:
                    childs=rpc_exec(act["res_model"],"read",child_ids,["id",field_parent]+field_names)
                    childs.reverse()
                    for child in childs:
                        child["_depth"]=obj["_depth"]+1
                        child["_expanded"]=False
                        objs_r.insert(i+1,child)
                        win_r.move(i+1,0)
                        win_r.insertln()
                        win_r.addstr(i+1,1+child["_depth"]*2,child["name"])
                        if child[field_parent]:
                            win_r.addch(i+1,child["_depth"]*2,"/")
                    obj["_expanded"]=True
                win_r.refresh()
        elif c==curses.KEY_LEFT:
            if mode=="r":
                i=screen.getyx()[0]-4
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
                    win_r.move(i+1,0)
                    win_r.deleteln()
                    folded=True
                win_r.refresh()
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
                win_l.chgat(select_l,0,24,curses.A_BOLD)
                select_l=y-2
                win_l.chgat(select_l,0,24,curses.A_REVERSE|curses.A_BOLD)

                win_r.clear()
                child_ids=rpc_exec(act["res_model"],"read",objs_l[select_l]["id"],[field_parent])[field_parent]
                objs_r=rpc_exec(act["res_model"],"read",child_ids,["id",field_parent]+field_names)
                y=0
                for obj in objs_r:
                    obj["_depth"]=0
                    obj["_expanded"]=False
                    win_r.addstr(y,1,obj["name"],curses.A_BOLD)
                    if obj[field_parent]:
                        win_r.addch(y,0,"/")
                    y+=1
            elif mode=="r":
                pass
            screen.refresh()
        elif c==ord("i"):
            screen.insertln()
            screen.refresh()
        elif c==ord("d"):
            screen.deleteln()
            screen.refresh()

def act_window_form(act):
    #log("act_window_form",act)
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
    global screen,tabs,content
    screen=stdscr.subwin(24,80,0,0)
    screen.keypad(1)
    user=rpc_exec("res.users","read",uid,["name","action_id","menu_id"])
    action(user["action_id"][0])

curses.wrapper(start)
