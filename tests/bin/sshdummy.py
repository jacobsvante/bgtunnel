from __future__ import print_function
import sys


def main():
    while True:
        print('Emulating login message from server...', file=sys.stdout)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        sys.exit('usage: ssh')
    else:
        main()
