# -*- coding: utf-8 -*-
"""
 @Time    : 2019/3/2 18:18
 @Author  : Wang Xin
 @Email   : wangxin_buaa@163.com
"""

from libs.criterion.criteria import MaskedL1Loss, MaskedMSELoss, L1_log
from libs.criterion.criteria import CriterionDSN, Criterion_No_DSN

key_to_criteria = {
    'l1': MaskedL1Loss,
    'l2': MaskedMSELoss,
    'l1_log': L1_log
}


def get_criteria(args):
    if args.criterion in key_to_criteria:
        criterion = key_to_criteria[args.criterion]()
    else:
        print('no available criterion methods named as ', args.arch)
        raise NotImplementedError

    if args.dsn:
        criterion = CriterionDSN(criterion=criterion)
    else:
        criterion = Criterion_No_DSN(opt=args, criterion=criterion)

    return criterion