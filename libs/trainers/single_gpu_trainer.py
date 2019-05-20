#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
@Time    : 2019-05-20 18:34
@Author  : Wang Xin
@Email   : wangxin_buaa@163.com
@File    : single_gpu_trainer.py
"""


import os
import time

import torch
import torch.nn.functional as F
from tqdm import tqdm

from libs import utils
from libs.criterion import get_criteria
from libs.metrics import AverageMeter, Result
from libs.scheduler import get_schedular, do_schedule


class trainer(object):

    def __init__(self, args, model, optimizer, start_iter, best_result=None):
        self.opt = args
        self.model = model.cuda()
        self.optimizer = optimizer
        self.scheduler = get_schedular(optimizer, args)
        self.criterion = get_criteria(args)

        # record file path
        self.output_directory = utils.get_save_path(args)
        self.best_txt = os.path.join(self.output_directory, 'best.txt')
        utils.write_config_file(args, self.output_directory)
        self.logger = utils.get_logger(self.output_directory)

        self.st_iter, self.ed_iter = start_iter, self.opt.max_iter

        # data loader
        from dataloaders import create_loader
        self.train_loader = create_loader(self.opt, mode='train')
        self.eval_loader = create_loader(self.opt, mode='val')

        if best_result:
            self.best_result = best_result
        else:
            self.best_result = Result()
            self.best_result.set_to_worst()

        # train parameters
        self.iter_save = len(self.train_loader)
        self.train_meter = AverageMeter()
        self.eval_meter = AverageMeter()
        self.metric = self.best_result.silog
        self.result = Result()

    def train_iter(self, it):
        # Clear gradients (ready to accumulate)
        self.optimizer.zero_grad()

        end = time.time()

        try:
            input, target = next(loader_iter)
        except:
            loader_iter = iter(self.train_loader)
            input, target = next(loader_iter)

        input, target = input.cuda(), target.cuda()
        data_time = time.time() - end

        # compute pred
        end = time.time()
        pred = self.model(input)  # @wx 注意输出

        loss = self.criterion(pred, target)
        loss.backward()  # compute gradient and do SGD step
        self.optimizer.step()

        gpu_time = time.time() - end

        # measure accuracy and record loss in each GPU
        self.result.set_to_worst()
        self.result.evaluate(pred[0], target, loss.item())
        self.train_meter.update(self.result, gpu_time, data_time, input.size(0))

        avg = self.train_meter.average()
        if it % self.opt.print_freq == 0:
            print('=> output: {}'.format(self.output_directory))
            print('Train Iter: [{0}/{1}]\t'
                  't_Data={data_time:.3f}({average.data_time:.3f}) '
                  't_GPU={gpu_time:.3f}({average.gpu_time:.3f})\n\t'
                  'Loss={Loss:.5f}(average.loss:.5f)'
                  'SILog={result.silog:.2f}({average.silog:.2f}) '
                  'sqErrorRel={result.squared_rel:.2f}({average.squared_rel:.2f}) '
                  'absErrorRel={result.absrel:.2f}({average.absrel:.2f}) '
                  'iRMSE={result.irmse:.2f}({average.irmse:.2f}) '.format(
                it, self.opt.max_iter, data_time=data_time,
                gpu_time=gpu_time, Loss=loss.item(), result=self.result, average=avg))

            self.logger.add_scalar('Train/Loss', avg.loss, it)
            self.logger.add_scalar('Train/SILog', avg.silog, it)
            self.logger.add_scalar('Train/sqErrorRel', avg.squared_rel, it)
            self.logger.add_scalar('Train/absErrorRel', avg.absrel, it)
            self.logger.add_scalar('Train/iRMSE', avg.irmse, it)

    def eval(self, it):

        skip = len(self.eval_loader) // 9  # save images every skip iters
        self.eval_meter.reset()

        for i, (input, target) in enumerate(self.eval_loader):

            end = time.time()
            input, target = input.cuda(), target.cuda()

            data_time = time.time() - end

            # compute output
            end = time.time()
            with torch.no_grad():
                pred = self.model(input)

            gpu_time = time.time() - end

            # measure accuracy and record loss
            # print(input.size(0))

            self.result.set_to_worst()
            self.result.evaluate(pred[0], target)
            self.eval_meter.update(self.result, gpu_time, data_time, input.size(0))

            if i % skip == 0:
                pred = pred[0][0]

                # save 8 images for visualization
                h, w = target.size(2), target.size(3)
                if h != pred.size(2) or w != pred.size(3):
                    pred = F.interpolate(input=pred, size=(h, w), mode='bilinear', align_corners=True)

                data = input[0]
                target = target[0]
                pred = pred[0]

            if self.opt.modality == 'd':
                img_merge = None
            else:
                if self.opt.modality == 'rgb':
                    rgb = data
                elif self.opt.modality == 'rgbd':
                    rgb = data[:3, :, :]
                    depth = data[3:, :, :]

                if i == 0:
                    if self.opt.modality == 'rgbd':
                        img_merge = utils.merge_into_row_with_gt(rgb, depth, target, pred)
                    else:
                        img_merge = utils.merge_into_row(rgb, target, pred)

                elif (i < 8 * skip) and (i % skip == 0):
                    if self.opt.modality == 'rgbd':
                        row = utils.merge_into_row_with_gt(rgb, depth, target, pred)
                    else:
                        row = utils.merge_into_row(rgb, target, pred)
                    img_merge = utils.add_row(img_merge, row)
                elif i == 8 * skip:
                    filename = self.output_directory + '/comparison_' + str(it) + '.png'
                    utils.save_image(img_merge, filename)

            if (i + 1) % self.opt.print_freq == 0:
                print('Test: [{0}/{1}]\t'
                      't_GPU={gpu_time:.3f}({average.gpu_time:.3f})\n\t'
                      'SILog={result.silog:.2f}({average.silog:.2f}) '
                      'sqErrorRel={result.squared_rel:.2f}({average.squared_rel:.2f}) '
                      'absErrorRel={result.absrel:.2f}({average.absrel:.2f}) '
                      'iRMSE={result.irmse:.3f}({average.irmse:.3f}) '.format(
                    i + 1, len(self.eval_loader), gpu_time=gpu_time, result=result, average=self.eval_meter.average()))

        avg = self.eval_meter.average()

        print('\n*\n'
              'SILog={average.silog:.2f}\n'
              'sqErrorRel={average.squared_rel:.2f}\n'
              'absErrorRel={average.absrel:.2f}\n'
              'iRMSE={average.irmse:.2f}\n'
              't_GPU={time:.3f}\n'.format(
            average=avg, time=avg.gpu_time))

        self.logger.add_scalar('Test/SILog', avg.silog, it)
        self.logger.add_scalar('Test/sqErrorRel', avg.squared_rel, it)
        self.logger.add_scalar('Test/absErrorRel', avg.absrel, it)
        self.logger.add_scalar('Test/iRMSE', avg.irmse, it)

    def train_eval(self):

        for it in tqdm(range(self.st_iter, self.ed_iter + 1), total=self.ed_iter - self.st_iter + 1,
                       leave=False, dynamic_ncols=True):
            self.model.train()
            self.train_iter(it)

            if it % self.iter_save == 0:
                self.model.eval()
                self.eval(it)

                self.metric = self.eval_meter.average().silog
                train_avg = self.train_meter.average()
                eval_avg = self.eval_meter.average()

                self.logger.add_scalars('TrainVal/SILog',
                                   {'train_SILog': train_avg.silog, 'test_SILog': eval_avg.silog}, it)
                self.logger.add_scalars('TrainVal/sqErrorRel',
                                   {'train_sqErrorRel': train_avg.squared_rel, 'test_sqErrorRel': eval_avg.squared_rel},
                                   it)
                self.logger.add_scalars('TrainVal/absErrorRel',
                                   {'train_absErrorRel': train_avg.absrel, 'test_absErrorRel': eval_avg.absrel}, it)
                self.logger.add_scalars('TrainVal/iRMSE',
                                   {'train_iRMSE': train_avg.irmse, 'test_iRMSE': eval_avg.irmse}, it)
                self.train_meter.reset()

                # save the change of learning_rate
                for i, param_group in enumerate(self.optimizer.param_groups):
                    old_lr = float(param_group['lr'])
                    self.logger.add_scalar('Lr/lr_' + str(i), old_lr, it)

                # remember best rmse and save checkpoint
                is_best = eval_avg.silog < self.best_result.silog
                if is_best:
                    self.best_result = eval_avg
                    with open(self.best_txt, 'w') as txtfile:
                        txtfile.write(
                            "epoch={}, SILog={:.2f}, sqErrorRel={:.2f}, absErrorRel={:.2f}, iRMSE={:.2f}, t_gpu={:.4f}".
                                format(it, eval_avg.silog, eval_avg.squared_rel, eval_avg.absrel, eval_avg.irmse,
                                       eval_avg.gpu_time))

                # save checkpoint for each epoch
                utils.save_checkpoint({
                    'args': self.opt,
                    'epoch': it,
                    'state_dict': self.model.state_dict(),
                    'best_result': self.best_result,
                    'optimizer': self.optimizer,
                }, is_best, it, self.output_directory)

            # Update learning rate
            do_schedule(self.opt, self.scheduler, it=it, len=self.iter_save, metrics=self.metric)

        self.logger.close()
