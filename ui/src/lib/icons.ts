// Registro Iconify: cada icono Phosphor light usado en la UI se importa una sola vez
// aquí y se registra con addIcon() para que el wrapper <Icon> lo resuelva por nombre.
//
// Convención (igual que todoconta-apps/web): Phosphor termina en -light (stroke 1.5px).
//
// Para agregar un icono:
//   1. import del JSON desde @iconify-icons/ph/<name>-light
//   2. addIcon("ph:<name>-light", <importedJson>)
//   3. usar en JSX: <Icon icon="ph:<name>-light" className="..." />

import { addIcon } from '@iconify/react';

import arrowCounterClockwise from '@iconify-icons/ph/arrow-counter-clockwise-light';
import arrowDown from '@iconify-icons/ph/arrow-down-light';
import arrowLeft from '@iconify-icons/ph/arrow-left-light';
import arrowUp from '@iconify-icons/ph/arrow-up-light';
import arrowsClockwise from '@iconify-icons/ph/arrows-clockwise-light';
import arrowsDownUp from '@iconify-icons/ph/arrows-down-up-light';
import buildings from '@iconify-icons/ph/buildings-light';
import calendar from '@iconify-icons/ph/calendar-light';
import calendarCheck from '@iconify-icons/ph/calendar-check-light';
import caretDown from '@iconify-icons/ph/caret-down-light';
import caretRight from '@iconify-icons/ph/caret-right-light';
import caretUp from '@iconify-icons/ph/caret-up-light';
import check from '@iconify-icons/ph/check-light';
import checkCircle from '@iconify-icons/ph/check-circle-light';
import checkSquare from '@iconify-icons/ph/check-square-light';
import circle from '@iconify-icons/ph/circle-light';
import circleNotch from '@iconify-icons/ph/circle-notch-light';
import clipboardText from '@iconify-icons/ph/clipboard-text-light';
import clockCounterClockwise from '@iconify-icons/ph/clock-counter-clockwise-light';
import currencyDollar from '@iconify-icons/ph/currency-dollar-light';
import database from '@iconify-icons/ph/database-light';
import dotsSixVertical from '@iconify-icons/ph/dots-six-vertical-light';
import downloadSimple from '@iconify-icons/ph/download-simple-light';
import eye from '@iconify-icons/ph/eye-light';
import file from '@iconify-icons/ph/file-light';
import filePdf from '@iconify-icons/ph/file-pdf-light';
import fileText from '@iconify-icons/ph/file-text-light';
import folder from '@iconify-icons/ph/folder-light';
import folderOpen from '@iconify-icons/ph/folder-open-light';
import folders from '@iconify-icons/ph/folders-light';
import gear from '@iconify-icons/ph/gear-light';
import hardDrives from '@iconify-icons/ph/hard-drives-light';
import key from '@iconify-icons/ph/key-light';
import lock from '@iconify-icons/ph/lock-light';
import magnifyingGlass from '@iconify-icons/ph/magnifying-glass-light';
import packageIcon from '@iconify-icons/ph/package-light';
import pencilSimple from '@iconify-icons/ph/pencil-simple-light';
import plus from '@iconify-icons/ph/plus-light';
import prohibit from '@iconify-icons/ph/prohibit-light';
import radioButton from '@iconify-icons/ph/radio-button-light';
import scroll from '@iconify-icons/ph/scroll-light';
import sealCheck from '@iconify-icons/ph/seal-check-light';
import shieldCheck from '@iconify-icons/ph/shield-check-light';
import square from '@iconify-icons/ph/square-light';
import squaresFour from '@iconify-icons/ph/squares-four-light';
import trash from '@iconify-icons/ph/trash-light';
import uploadSimple from '@iconify-icons/ph/upload-simple-light';
import warning from '@iconify-icons/ph/warning-light';
import warningCircle from '@iconify-icons/ph/warning-circle-light';
import x from '@iconify-icons/ph/x-light';
import xCircle from '@iconify-icons/ph/x-circle-light';

// Íconos adicionales registrados para que el bundle empacado funcione 100%
// offline. Sin esto, Iconify cae a su API remota (`api.iconify.design/ph.json`)
// para resolver el ícono por nombre — falla bajo Electron empacado (sin red /
// origen distinto) y el ícono no aparece.
import archive from '@iconify-icons/ph/archive-light';
import archiveTray from '@iconify-icons/ph/archive-tray-light';
import arrowClockwise from '@iconify-icons/ph/arrow-clockwise-light';
import arrowRight from '@iconify-icons/ph/arrow-right-light';
import arrowSquareOut from '@iconify-icons/ph/arrow-square-out-light';
import arrowUpRight from '@iconify-icons/ph/arrow-up-right-light';
import bell from '@iconify-icons/ph/bell-light';
import bellSlash from '@iconify-icons/ph/bell-slash-light';
import caretLeft from '@iconify-icons/ph/caret-left-light';
import chartBar from '@iconify-icons/ph/chart-bar-light';
import checkCircleFill from '@iconify-icons/ph/check-circle-fill';
import cloudArrowDown from '@iconify-icons/ph/cloud-arrow-down-light';
import cloudArrowUp from '@iconify-icons/ph/cloud-arrow-up-light';
import copy from '@iconify-icons/ph/copy-light';
import currencyCircleDollar from '@iconify-icons/ph/currency-circle-dollar-light';
import desktop from '@iconify-icons/ph/desktop-light';
import fileArrowUp from '@iconify-icons/ph/file-arrow-up-light';
import fileCsv from '@iconify-icons/ph/file-csv-light';
import fileXls from '@iconify-icons/ph/file-xls-light';
import files from '@iconify-icons/ph/files-light';
import funnel from '@iconify-icons/ph/funnel-light';
import hourglassMedium from '@iconify-icons/ph/hourglass-medium-light';
import info from '@iconify-icons/ph/info-light';
import lifebuoy from '@iconify-icons/ph/lifebuoy-light';
import lightning from '@iconify-icons/ph/lightning-light';
import link from '@iconify-icons/ph/link-light';
import listMagnifyingGlass from '@iconify-icons/ph/list-magnifying-glass-light';
import listNumbers from '@iconify-icons/ph/list-numbers-light';
import moon from '@iconify-icons/ph/moon-light';
import percent from '@iconify-icons/ph/percent-light';
import question from '@iconify-icons/ph/question-light';
import receipt from '@iconify-icons/ph/receipt-light';
import rocket from '@iconify-icons/ph/rocket-light';
import sparkle from '@iconify-icons/ph/sparkle-light';
import bank from '@iconify-icons/ph/bank-light';
import starFill from '@iconify-icons/ph/star-fill';
import star from '@iconify-icons/ph/star-light';
import sun from '@iconify-icons/ph/sun-light';
import trendUp from '@iconify-icons/ph/trend-up-light';
import upload from '@iconify-icons/ph/upload-light';
import usersThree from '@iconify-icons/ph/users-three-light';
import wallet from '@iconify-icons/ph/wallet-light';
import warningOctagon from '@iconify-icons/ph/warning-octagon-light';

// Rediseño v2: shell (sidebar colapsable, cuenta, Ayuda, status bar).
import bookOpen from '@iconify-icons/ph/book-open-light';
import chatCircle from '@iconify-icons/ph/chat-circle-light';
import clock from '@iconify-icons/ph/clock-light';
import creditCard from '@iconify-icons/ph/credit-card-light';
import crownSimple from '@iconify-icons/ph/crown-simple-light';
import crownSimpleFill from '@iconify-icons/ph/crown-simple-fill';
import envelopeSimple from '@iconify-icons/ph/envelope-simple-light';
import minus from '@iconify-icons/ph/minus-light';
import play from '@iconify-icons/ph/play-light';
import sidebarSimple from '@iconify-icons/ph/sidebar-simple-light';
import signOut from '@iconify-icons/ph/sign-out-light';
import user from '@iconify-icons/ph/user-light';

// Login v2 (login en-app con contraseña / código).
import eyeSlash from '@iconify-icons/ph/eye-slash-light';

// Atajos de teclado (card en /ayuda).
import keyboard from '@iconify-icons/ph/keyboard-light';

// API keys + conexión MCP (Ajustes → API y conexiones).
import plugsConnected from '@iconify-icons/ph/plugs-connected-light';

// Equipo (Ajustes → Equipo: miembros, invitar, roles).
import users from '@iconify-icons/ph/users-light';
import userPlus from '@iconify-icons/ph/user-plus-light';
import shield from '@iconify-icons/ph/shield-light';
import envelope from '@iconify-icons/ph/envelope-light';

// Calculadoras (nav + cards del índice + export premium).
import calculator from '@iconify-icons/ph/calculator-light';
import factory from '@iconify-icons/ph/factory-light';
import gift from '@iconify-icons/ph/gift-light';
import handshake from '@iconify-icons/ph/handshake-light';
import heartbeat from '@iconify-icons/ph/heartbeat-light';
import lockSimple from '@iconify-icons/ph/lock-simple-light';
import printer from '@iconify-icons/ph/printer-light';
import scales from '@iconify-icons/ph/scales-light';

// Navegación por espacios (F3): riel, panel, ⌘K con órdenes y destinos Pronto.
import arrowElbowDownLeft from '@iconify-icons/ph/arrow-elbow-down-left-light';
import books from '@iconify-icons/ph/books-light';
import calendarBlank from '@iconify-icons/ph/calendar-blank-light';
import caretDoubleLeft from '@iconify-icons/ph/caret-double-left-light';
import caretDoubleRight from '@iconify-icons/ph/caret-double-right-light';
import certificate from '@iconify-icons/ph/certificate-light';
import chartLineUp from '@iconify-icons/ph/chart-line-up-light';
import chartPieSlice from '@iconify-icons/ph/chart-pie-slice-light';
import fileArrowDown from '@iconify-icons/ph/file-arrow-down-light';
import fileCode from '@iconify-icons/ph/file-code-light';
import fingerprint from '@iconify-icons/ph/fingerprint-light';
import flask from '@iconify-icons/ph/flask-light';
import fileZip from '@iconify-icons/ph/file-zip-light';
import handCoins from '@iconify-icons/ph/hand-coins-light';
import houseSimple from '@iconify-icons/ph/house-simple-light';
import identificationCard from '@iconify-icons/ph/identification-card-light';
import paperPlaneTilt from '@iconify-icons/ph/paper-plane-tilt-light';
import receiptX from '@iconify-icons/ph/receipt-x-light';
import stamp from '@iconify-icons/ph/stamp-light';
import toolbox from '@iconify-icons/ph/toolbox-light';

addIcon('ph:arrow-counter-clockwise-light', arrowCounterClockwise);
addIcon('ph:arrow-down-light', arrowDown);
addIcon('ph:arrow-left-light', arrowLeft);
addIcon('ph:arrow-up-light', arrowUp);
addIcon('ph:arrows-clockwise-light', arrowsClockwise);
addIcon('ph:arrows-down-up-light', arrowsDownUp);
addIcon('ph:buildings-light', buildings);
addIcon('ph:calendar-light', calendar);
addIcon('ph:calendar-check-light', calendarCheck);
addIcon('ph:caret-down-light', caretDown);
addIcon('ph:caret-right-light', caretRight);
addIcon('ph:caret-up-light', caretUp);
addIcon('ph:check-light', check);
addIcon('ph:check-circle-light', checkCircle);
addIcon('ph:check-square-light', checkSquare);
addIcon('ph:circle-light', circle);
addIcon('ph:circle-notch-light', circleNotch);
addIcon('ph:clipboard-text-light', clipboardText);
addIcon('ph:clock-counter-clockwise-light', clockCounterClockwise);
addIcon('ph:currency-dollar-light', currencyDollar);
addIcon('ph:database-light', database);
addIcon('ph:dots-six-vertical-light', dotsSixVertical);
addIcon('ph:download-simple-light', downloadSimple);
addIcon('ph:eye-light', eye);
addIcon('ph:file-light', file);
addIcon('ph:file-pdf-light', filePdf);
addIcon('ph:file-text-light', fileText);
addIcon('ph:folder-light', folder);
addIcon('ph:folder-open-light', folderOpen);
addIcon('ph:folders-light', folders);
addIcon('ph:gear-light', gear);
addIcon('ph:hard-drives-light', hardDrives);
addIcon('ph:key-light', key);
addIcon('ph:lock-light', lock);
addIcon('ph:magnifying-glass-light', magnifyingGlass);
addIcon('ph:package-light', packageIcon);
addIcon('ph:pencil-simple-light', pencilSimple);
addIcon('ph:plus-light', plus);
addIcon('ph:prohibit-light', prohibit);
addIcon('ph:radio-button-light', radioButton);
addIcon('ph:scroll-light', scroll);
addIcon('ph:seal-check-light', sealCheck);
addIcon('ph:square-light', square);
addIcon('ph:shield-check-light', shieldCheck);
addIcon('ph:squares-four-light', squaresFour);
addIcon('ph:trash-light', trash);
addIcon('ph:upload-simple-light', uploadSimple);
addIcon('ph:warning-light', warning);
addIcon('ph:warning-circle-light', warningCircle);
addIcon('ph:x-light', x);
addIcon('ph:x-circle-light', xCircle);

// Registro de los íconos adicionales (ver bloque de imports arriba).
addIcon('ph:archive-light', archive);
addIcon('ph:archive-tray-light', archiveTray);
addIcon('ph:arrow-clockwise-light', arrowClockwise);
addIcon('ph:arrow-right-light', arrowRight);
addIcon('ph:arrow-square-out-light', arrowSquareOut);
addIcon('ph:arrow-up-right-light', arrowUpRight);
addIcon('ph:bell-light', bell);
addIcon('ph:bell-slash-light', bellSlash);
addIcon('ph:caret-left-light', caretLeft);
addIcon('ph:chart-bar-light', chartBar);
addIcon('ph:check-circle-fill', checkCircleFill);
addIcon('ph:cloud-arrow-down-light', cloudArrowDown);
addIcon('ph:cloud-arrow-up-light', cloudArrowUp);
addIcon('ph:copy-light', copy);
addIcon('ph:currency-circle-dollar-light', currencyCircleDollar);
addIcon('ph:desktop-light', desktop);
addIcon('ph:file-arrow-up-light', fileArrowUp);
addIcon('ph:file-csv-light', fileCsv);
addIcon('ph:file-xls-light', fileXls);
addIcon('ph:files-light', files);
addIcon('ph:funnel-light', funnel);
addIcon('ph:hourglass-medium-light', hourglassMedium);
addIcon('ph:info-light', info);
addIcon('ph:lifebuoy-light', lifebuoy);
addIcon('ph:lightning-light', lightning);
addIcon('ph:link-light', link);
addIcon('ph:list-magnifying-glass-light', listMagnifyingGlass);
addIcon('ph:list-numbers-light', listNumbers);
addIcon('ph:moon-light', moon);
addIcon('ph:percent-light', percent);
addIcon('ph:question-light', question);
addIcon('ph:receipt-light', receipt);
addIcon('ph:rocket-light', rocket);
addIcon('ph:sparkle-light', sparkle);
addIcon('ph:bank-light', bank);
addIcon('ph:star-fill', starFill);
addIcon('ph:star-light', star);
addIcon('ph:sun-light', sun);
addIcon('ph:trend-up-light', trendUp);
addIcon('ph:upload-light', upload);
addIcon('ph:users-three-light', usersThree);
addIcon('ph:wallet-light', wallet);
addIcon('ph:warning-octagon-light', warningOctagon);

// Rediseño v2 (ver bloque de imports arriba).
addIcon('ph:book-open-light', bookOpen);
addIcon('ph:chat-circle-light', chatCircle);
addIcon('ph:clock-light', clock);
addIcon('ph:credit-card-light', creditCard);
addIcon('ph:crown-simple-light', crownSimple);
addIcon('ph:crown-simple-fill', crownSimpleFill);
addIcon('ph:envelope-simple-light', envelopeSimple);
addIcon('ph:minus-light', minus);
addIcon('ph:play-light', play);
addIcon('ph:sidebar-simple-light', sidebarSimple);
addIcon('ph:sign-out-light', signOut);
addIcon('ph:user-light', user);

// Login v2 (ver bloque de imports arriba).
addIcon('ph:eye-slash-light', eyeSlash);

// Atajos de teclado (ver bloque de imports arriba).
addIcon('ph:keyboard-light', keyboard);

// API keys + conexión MCP (ver bloque de imports arriba).
addIcon('ph:plugs-connected-light', plugsConnected);

// Equipo (ver bloque de imports arriba).
addIcon('ph:users-light', users);
addIcon('ph:user-plus-light', userPlus);
addIcon('ph:shield-light', shield);
addIcon('ph:envelope-light', envelope);

// Calculadoras (ver bloque de imports arriba).
addIcon('ph:calculator-light', calculator);
addIcon('ph:factory-light', factory);
addIcon('ph:gift-light', gift);
addIcon('ph:handshake-light', handshake);
addIcon('ph:heartbeat-light', heartbeat);
addIcon('ph:lock-simple-light', lockSimple);
addIcon('ph:printer-light', printer);
addIcon('ph:scales-light', scales);

// Navegación por espacios (ver bloque de imports arriba).
addIcon('ph:arrow-elbow-down-left-light', arrowElbowDownLeft);
addIcon('ph:books-light', books);
addIcon('ph:calendar-blank-light', calendarBlank);
addIcon('ph:caret-double-left-light', caretDoubleLeft);
addIcon('ph:caret-double-right-light', caretDoubleRight);
addIcon('ph:certificate-light', certificate);
addIcon('ph:chart-line-up-light', chartLineUp);
addIcon('ph:chart-pie-slice-light', chartPieSlice);
addIcon('ph:file-arrow-down-light', fileArrowDown);
addIcon('ph:file-code-light', fileCode);
addIcon('ph:fingerprint-light', fingerprint);
addIcon('ph:flask-light', flask);
addIcon('ph:file-zip-light', fileZip);
addIcon('ph:hand-coins-light', handCoins);
addIcon('ph:house-simple-light', houseSimple);
addIcon('ph:identification-card-light', identificationCard);
addIcon('ph:paper-plane-tilt-light', paperPlaneTilt);
addIcon('ph:receipt-x-light', receiptX);
addIcon('ph:stamp-light', stamp);
addIcon('ph:toolbox-light', toolbox);
