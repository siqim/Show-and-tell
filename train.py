# -*- coding: utf-8 -*-
"""
Created in Oct 2018
"""

import os
import sys
import time
import pickle
from tensorboardX import SummaryWriter

import torch
import torch.nn as nn
import torch.nn.utils.rnn as rnn_utils
import torch.optim as optim
from torchvision import transforms

from models import CNN, RNN
from utils import save_model, load_model
from dataloader import MSCOCO, collate_fn

#MODEL_NAME = sys.argv[1]
MODEL_NAME = 'SGD-17000-NOV10'
#MODEL_NAME = 'ADAM-13000-NOAVGPOOL-NOV15'
NUM_WORKERS = 0
EPOCHS = 50
#DEBUG = True
DEBUG = False

print(MODEL_NAME, 'starts running!')

init_params_file = '../model_params/' + MODEL_NAME
if os.path.isfile(init_params_file):
    # if resume training, load hypermeters.
    print('Loading params...')
    params = pickle.load(open(init_params_file, 'rb'))

    LR = params['LR']
    VOCAB_SIZE = params['VOCAB_SIZE']
    NO_WORD_EMBEDDINGS = params['NO_WORD_EMBEDDINGS']
    HIDDEN_SIZE = params['HIDDEN_SIZE']
    BATCH_SIZE = params['BATCH_SIZE']
    NUM_LAYERS = params['NUM_LAYERS']
    WEIGHT_DECAY = params['WEIGHT_DECAY']
    RNN_DROPOUT = params['RNN_DROPOUT']
    CNN_DROPOUT = params['CNN_DROPOUT']
    ADAM_FLAG = params['ADAM_FLAG']

    train_imagepaths_and_captions = params['train_imagepaths_and_captions']
    val_imagepaths_and_captions = params['val_imagepaths_and_captions']
    pretrained_cnn_file = params['pretrained_cnn_file']
    pretrained_word_embeddings_file = params['pretrained_word_embeddings_file']

    transform_train = params['transform_train']
    transform_val = params['transform_val']

    print('Loading models...')
    encoder = params['encoder']
    decoder = params['decoder']
    encoder.cuda()
    decoder.cuda()

    print('Loading optimizer...')
    optimizer = params['optimizer']

else:
    # if tune a new set of hyperparameters or new models, change parameters below before training.
    print('Initilizing params...')
    LR = 0.0001
    WEIGHT_DECAY = 0.0001
    GRAD_CLIP = 5.0
    RNN_DROPOUT = 0.5
    CNN_DROPOUT = 0.5

    VOCAB_SIZE = 13000 + 3
    NO_WORD_EMBEDDINGS = 512
    HIDDEN_SIZE = 512
    BATCH_SIZE = 128
    NUM_LAYERS = 1
    ADAM_FLAG = True


    train_imagepaths_and_captions = '../preprocessed_data/imagepaths_captions.train'
    val_imagepaths_and_captions = '../preprocessed_data/imagepaths_captions.val'
    pretrained_cnn_file = '../pre_trained/resnet101-5d3b4d8f.pth'
#    pretrained_word_embeddings_file = '../preprocessed_data/embeddings'
    pretrained_word_embeddings_file = None


    transform_train = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ColorJitter(
                brightness=0.1*torch.randn(1),
                contrast=0.1*torch.randn(1),
                saturation=0.1*torch.randn(1),
                hue=0.1*torch.randn(1)),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]) # copy from github
    ])

    transform_val = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]) # copy from github
    ])

#        transforms.Normalize([0.4731, 0.4467, 0.4059], [0.2681, 0.2627, 0.2774]) # calculated by our code.

    params = {'LR': LR, 'VOCAB_SIZE': VOCAB_SIZE, 'NO_WORD_EMBEDDINGS': NO_WORD_EMBEDDINGS, 'HIDDEN_SIZE': HIDDEN_SIZE,
              'BATCH_SIZE': BATCH_SIZE, 'NUM_LAYERS': NUM_LAYERS, 'train_imagepaths_and_captions': train_imagepaths_and_captions,
              'val_imagepaths_and_captions': val_imagepaths_and_captions, 'pretrained_cnn_file': pretrained_cnn_file,
              'pretrained_word_embeddings_file': pretrained_word_embeddings_file, 'transform_train': transform_train, 
              'transform_val': transform_val, 'WEIGHT_DECAY': WEIGHT_DECAY, 'ADAM_FLAG': ADAM_FLAG, 'RNN_DROPOUT':RNN_DROPOUT,
              'CNN_DROPOUT': CNN_DROPOUT}


    print('Initializing models...')
    encoder = CNN(NO_WORD_EMBEDDINGS, pretrained_cnn_file, freeze=True, dropout_prob=CNN_DROPOUT)
    decoder = RNN(VOCAB_SIZE, NO_WORD_EMBEDDINGS, hidden_size=HIDDEN_SIZE, num_layers=NUM_LAYERS,
                  pre_trained_file=pretrained_word_embeddings_file, freeze=False, dropout_prob=RNN_DROPOUT)
    params['encoder'] = encoder
    params['decoder'] = decoder
    encoder.cuda()
    decoder.cuda()

    print('Initializing optimizer...')
    model_paras = list(encoder.parameters()) + list(decoder.parameters())
    optimizer = optim.Adam(model_paras, lr=LR, weight_decay=WEIGHT_DECAY)
    params['optimizer'] = optimizer


    pickle.dump(params, open(init_params_file, 'wb'))


model_dir = '../saved_model/' + MODEL_NAME + '/'
log_dir = '../logs/' + MODEL_NAME + '/'
if not os.path.isdir(model_dir):
    os.mkdir(model_dir)
if not os.path.isdir(log_dir):
    os.mkdir(log_dir)

# initialize accumulators.
current_epoch = 1
batch_step_count = 1
time_used_global = 0.0
checkpoint = 1


# load lastest model to resume training
model_list = os.listdir(model_dir)
if model_list:
    print('Loading lastest checkpoint...')
    state = load_model(model_dir, model_list)
    encoder.load_state_dict(state['encoder'])
    decoder.load_state_dict(state['decoder'])
    optimizer.load_state_dict(state['optimizer'])
    current_epoch = state['epoch'] + 1
    time_used_global = state['time_used_global']
    batch_step_count = state['batch_step_count']

criterion = nn.CrossEntropyLoss()

print('Loading dataset...')
trainset = MSCOCO(VOCAB_SIZE, train_imagepaths_and_captions, transform_train)
trainloader = torch.utils.data.DataLoader(dataset=trainset, batch_size=BATCH_SIZE, collate_fn=collate_fn,
                                          shuffle=True, drop_last=False, num_workers=NUM_WORKERS)

valset = MSCOCO(VOCAB_SIZE, val_imagepaths_and_captions, transform_val)
valloader = torch.utils.data.DataLoader(dataset=valset, batch_size=BATCH_SIZE, collate_fn=collate_fn, 
                                        shuffle=False, drop_last=False, num_workers=NUM_WORKERS)
writer = SummaryWriter(log_dir)
for epoch in range(current_epoch, EPOCHS+1):
    start_time_epoch = time.time()
    encoder.train() # to get BN layers work normally.
    decoder.train()

    print('[%d] epoch starts training...'%epoch)
    trainloss = 0.0
    for batch_idx, (images, captions, lengths) in enumerate(trainloader, 1):
        
        images = images.cuda()
        captions = captions.cuda()
        lengths = lengths.cuda()
        # when doing forward propagation, we do not input end word key; when calculating loss, we do not count start word key.
        lengths -= 1
        # throw out the start word key when calculating loss.
        targets = rnn_utils.pack_padded_sequence(captions[:, 1:], lengths, batch_first=True)[0]
        
        encoder.zero_grad()
        decoder.zero_grad()
        
        image_embeddings = encoder(images)
        # throw out the end word key when doing forward propagation.
        generated_captions = decoder(image_embeddings, captions[:, :-1], lengths)

        loss = criterion(generated_captions, targets)
        trainloss += loss

        loss.backward()
        
        # avoid exploding gradient
        if GRAD_CLIP is not None:
            for group in optimizer.param_groups:
                for p in group['params']:
                    if p.grad is not None:
                        p.grad.data.clamp_(-GRAD_CLIP, GRAD_CLIP)
                    
                    if ADAM_FLAG:
                        state = optimizer.state[p]
                        if('step' in state and state['step']>=1024):
                            state['step'] = 1000
        # avoid overflow error of ADAM optimizer in the BWs.
        elif ADAM_FLAG:
            for group in optimizer.param_groups:
                for p in group['params']:
                    state = optimizer.state[p]
                    if('step' in state and state['step']>=1024):
                        state['step'] = 1000

        optimizer.step()
        
        if batch_idx % 50 == 0:
            writer.add_scalar('batch/training_loss', loss, batch_step_count)
            batch_step_count += 1
            print('[%d] epoch, [%d] batch, [%.4f] loss, [%.2f] min used.'
                  %(epoch, batch_idx, loss, (time.time()-start_time_epoch)/60))

        if DEBUG:
            break
    trainloss /= batch_idx

    print('[%d] epoch starts validating...'%epoch)
    with torch.no_grad():
        encoder.eval()
        decoder.eval()
        valloss = 0.0
        for batch_idx, (images, captions, lengths) in enumerate(valloader, 1):

            images = images.cuda()
            captions = captions.cuda()
            lengths = lengths.cuda()
            lengths -= 1
            targets = rnn_utils.pack_padded_sequence(captions[:, 1:], lengths, batch_first=True)[0]

            image_embeddings = encoder(images)
            generated_captions = decoder(image_embeddings, captions[:, :-1], lengths)
    
            loss = criterion(generated_captions, targets)
    
            valloss += loss
    
            if DEBUG:
                break
        valloss /= batch_idx


    time_used_epoch = time.time() - start_time_epoch
    time_used_global += time_used_epoch


    writer.add_scalar('epoch/training_loss', trainloss, epoch)
    writer.add_scalar('epoch/validation_loss', valloss, epoch)
    print('[%d] epoch has finished. [%.4f] training loss, [%.4f] validation loss, [%.2f] min used this epoch, [%.2f] hours used in total'
          %(epoch, trainloss, valloss, time_used_epoch/60, time_used_global/3600))

    if epoch % checkpoint == 0:
        print('Saving model!')
        save_model(MODEL_NAME, model_dir, epoch, batch_step_count, time_used_global, optimizer, encoder, decoder)
        
    if DEBUG:
        break

writer.close()
