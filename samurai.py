#! /usr/bin/env python
'''
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
    
This programm is a interface to the basic sipgate VOIP API.
- Use the URI management to set calls


Dependencies:
    vobject
    
Unfinished:
    - Change server answer handling to Exceptions
    - set up a balance class
    Session
        - Multisession initiate
        - Scheduled session initiate
        - delete session instance if session is closed?
    Phonebook
        - useful searching?
'''

__author__ = 'merten@tabinin.eu'
__version__ = 'devel'


import xmlrpclib
import re
import socket

import vobject



SERVER_URL = 'samurai.sipgate.net/RPC2'     #The XML-RPC server-URI
DOMAIN = 'sipgate.de'

COUNTRY = '49'
LOCAL = '30'

VALID_DIGITS = ('0','1','2',
                '3','4','5',
                '6','7','8',
                '9')


def parseToURI(tel, domain=DOMAIN, country=COUNTRY, local=LOCAL):
    '''Parses a normal international phone number into a sipgate URI
    Returns None if number not valid
    Args:
        tel: telephone number as a string
        domian: provider Domain
    Returns:
        sip-url, None if telephone number is not valid
    '''
        
    '''Remove unvalid chars and spaces to make the number parseable.'''
    tempTel = ''
    for char in tel:
        if char  in (VALID_DIGITS + ('+',)):
            tempTel += char
    tel = tempTel
    
    '''Check for valid number '''
    localReg = re.search('^[1-9]\d+$',tel)
    cityReg = re.search('^0[1-9]\d+$',tel)
    countryReg = re.search('^(00|\+)[1-9]\d+$',tel)
    
    '''Format number into international format'''
    if localReg is not None:            #number is a local number
        tel = country + local + tel 
    elif cityReg is not None:           #number is a city number
        tel = tel.lstrip("0")           #remove leading zero
        tel = country + tel
    elif countryReg is not None:        #number is an international number
        tel = tel.lstrip("0")
    else:                               #number not valid
        raise InvalidNumberError("Invalid Number: " +  tel)

    return 'sip:' + tel + '@' + DOMAIN
    
    
class InvalidNumberError(Exception):
    '''Exception for number parser'''
    
class UnexpectedAnswerError(Exception):
    '''Exception for unexpected server messages'''
    
    
class Server():
    '''Handler for server connection and server calls'''
    
    def __init__(self,username, password, serverURL=SERVER_URL):
        '''Initiates a new server connection
        Args:
            username: username for your account
            password: password for your account
            serverURL: server URL if not default'''
            
        '''LoginURI in form 'https://username:password@samurai.sipgate.net/RPC2'''
        uri = 'https://' + username + ':' + password + '@' + serverURL
        
        try:
            self.server = xmlrpclib.ServerProxy(uri)
        except socket.error as e:
            print e
            
    def call(self, methodName, **kwargs):
        '''Call a method on the server
        Args:
            methodName: full method name  e.g. 'system.listMethods'
            method arguments
        '''
        
        try:
            expr = 'self.server.' + methodName + '(' + kwargs.__repr__() + ')'
            return eval(expr)
        except socket.error as e:
            statusCode, statusString = e.errno , e.strerror
            return {'StatusCode' : statusCode, 'StatusString' : statusString }
        except xmlrpclib.Fault as e:
            faultCode, faultString = e.faultCode, e.faultString
            return {'StatusCode' : faultCode, 'StatusString' : faultString }


class Account():
    '''Every instance of this class manages a single sipgate acount
    '''
    
    def __init__(self, username='',password=''):
        '''
        Args:
            username: username for your account
            password: password for your account
        '''
        
        self.phonebook = Phonebook()
        self.balance = None		
        
        self.uri = []        #All managed URIs in your account
        self.server = Server(username,password)
        
    def getServerStatus(self):
        '''Returns: Dict of server status messages
                Keys:
                    -SpecificationVersion
                    -ServerName
                    -ServerVersion
                    -ServerVendor
        '''
        return self.server.call('system.serverInfo')
    
    def updateManagedURI(self):
        '''Update the list of managed URIs'''
        
        answer = self.server.call('samurai.OwnUriListGet')
        
        if answer['StatusCode'] == 200:
            uriList = answer['OwnUriList']
            
            for element in uriList:
                self.uri.append(URI(self,
                                    element['SipUri'],
                                    element['TOS'],
                                    element['UriAlias'],
                                    element['E164Out'],
                                    element['E164In']))
                
    def updatePhonebook(self):
        ''' Update the local phonebook copy'''
        
        answer = self.server.call('samurai.PhonebookListGet')
            
        idList = []
        if answer['StatusCode'] == 200 :
            for entry in answer['PhonebookList']:
                idList.append(entry['EntryID'])
                
            answer = self.server.call('samurai.PhonebookEntryGet', EntryIDList=idList)
                
            if answer['StatusCode'] == 200:
                for entry in answer['EntryList']:
                    self.phonebook.addContact(entry['EntryID'],
                                              entry['EntryHash'],
                                              entry['Entry'])

    def updateBalance(self):
        '''Update the local balance copy
        set balance as specified in the samurai specification
        '''
        
        answer = self.server.call('samurai.BalanceGet')
            
        if answer['StatusCode'] == 200:
            self.balance = answer['CurrentBalance']
        
        
class URI():
    '''Manages the SIP-URIs services assosiated to the account.
    '''
    
    def __init__(self, account, sipURI, TOS, alias="", e164Out="", e164In=[] ):
        '''
        Args:
            account: Account assosiated to the session
            sip_uri: The unique SIP-URI
            tos: List of supported services
        '''
        
        self.sessions = {}
        self._account = account
        self._server = account.server
        self.sipURI = sipURI
        self.TOS = TOS
        
        self.alias = alias
        self.e164Out = e164Out
        self.e164In = e164In
        
        
    def call(self, remoteURI):
        '''Initiate a new voice session to remote URI
        Args:
            remote_uri: Target URI
        Returns:
            SessionID if successful otherwise None
        '''

        answer = self._server.call('samurai.SessionInitiate',
                                  LocalUri = self.sipURI,
                                  RemoteUri =  remoteURI,
                                  TOS = 'voice')
            
        if answer['StatusCode'] == 200:
            sessionID = answer['SessionID']
            self.sessions[sessionID] = Session(self._account,
                                               sessionID,
                                               'voice')
            return sessionID
        
        return None
        
    def fax(self, remoteURI, filename):
        '''Initiate a new fax session to remote URI
        Args:
            remote_uri: Target URI
            file: PDF filename
        Returns:
            SessionID if successful otherwise None
        '''
            
        try:
            file = open(filename)
            b64File = xmlrpclib.Binary(file.read())
            close(file)
        except IOError as e:
            print IOError
            return None
        else:
            answer = self._server.call('samurai.SessionInitiate',
                                      LocalUri = self.sipURI,
                                      RemoteUri = remoteURI,
                                      TOS = 'fax',
                                      Content = b64File)
            
            if answer['StatusCode'] == 200:
                sessionID = answer['SessionID']
                self.sessions[sessionID] = Session(self._account,
                                                   sessionID,
                                                   'fax')
                return sessionID
        
    def text(self, remoteURI,text=''):
        '''Send a text message to remote URI
        Args:
            remote_uri: Target URI
            text: The message
        Returns:
            SessionID if successful otherwise None
        '''

        answer = self._server.call('samurai.SessionInitiate',
                                  LocalUri = self.sip_uri,
                                  RemoteUri = remoteURI,
                                  TOS = 'text',
                                  Content = text)
            
        if answer['StatusCode'] == 200:
            sessionID = answer['SessionID']
            self.sessions[sessionID] = Session(self._account,
                                               sessionID,
                                               'text')
            return sessionID
        
        return None


class Session():
    '''Manages SIP session'''
    
    def __init__(self, account, sessionID, tos):
        '''Args:
            account: Account assosiated to the session
            sessionID: The id of the session
            tos: The type of service used in this session
        '''
        self.account = account
        self.server = account.server
        self.sessionID = sessionID
        self.tos = tos
                
    def getStatus(self):
        '''Returns: The current session status string
        if not successful None
        '''
        answer = self.server.call('samurai.SessionStatusGet', SessionID=self.sessionID)
            
        if answer['StatusCode'] == 200 or answer['StatusCode'] == 512:
            return answer['SessionStatus']
                
        return None
        
    def close(self):
        '''Close the active session, check Status to verify'''
        
        if self.account.isAvailable('samurai.SessionClose'):
            answer = self.account.server.samurai.SessionClose(self.sessionID)


class Phonebook():
    '''Represents the phonebook on the sipgate server.
    With the basic account you can't upload any contacts so
    it is useless for a read application.'''
    
    def __init__(self):
        '''Creates a new empty phonebook '''
        
        self.contactList = []
    
    def addContact(self, entryID, entryHash, entry):
        '''Creates a new vobject from vCard-string
        also saves the entryID and entryHash in a dictionary
        '''
        
        card = vobject.readOne(entry)
        self.contactList.append({'entryID' : entryID,
                                 'entryHash' : entryHash,
                                 'vCard' :  card})

#    def searchName(self,name):
#        '''Search for a name
#        returns:
#            new filtered phonebook
#        '''
#        
#        workPhonebook = phonebook()
#        
#        for entry in self.contactList:
#            if entry['vCard'].fn.value.find(name) != -1:
#                pb.addEntry(entry)
#                
#        return workPhonebook

    def getList(self):
        '''Returns:
            List of vobject vcards
        '''
        
        vcardList = []
        for entry in self.contactList:
            vcardList.append(entry['vCard'])
            
        return vcardList