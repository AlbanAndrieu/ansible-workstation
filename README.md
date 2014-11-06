# ansible-cmake

A role for installing workstation.

[![Build Status](https://api.travis-ci.org/AlbanAndrieu/ansible-workstation.png?branch=master)](https://travis-ci.org/AlbanAndrieu/ansible-workstation)
[![Galaxy](http://img.shields.io/badge/galaxy-workstation-blue.svg?style=flat-square)](https://galaxy.ansible.com/list#/roles/0000)
[![Tag](http://img.shields.io/github/tag/AlbanAndrieu/ansible-workstation.svg?style=flat-square)]()

## Actions

- This role is more a sample than a real role has it is specific to my need. it can be used as a template.
- Ensures that workstation is installed (using `apt`)

Usage example
------------

    - name: Install workstation
      hosts: workstation
      remote_user: root
    
      roles:
        - workstation      

Requirements
------------

none

Dependencies
------------

none

License
-------

MIT

#### Feedback, bug-reports, requests, ...

Are [welcome](https://github.com/AlbanAndrieu/ansible-workstation/issues)!
